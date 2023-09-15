# Lambda Function to deploy ALB Controller Add-on
# Reference Link : https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html
import base64
import os
import logging
import re
import boto3
import requests
import yaml
import time
from botocore.signers import RequestSigner
from kubernetes import client, config, utils


STS_TOKEN_EXPIRES_IN = 60
session = boto3.session.Session()
sts = session.client('sts')
service_id = sts.meta.service_model.service_id
cluster_name = os.environ["CLUSTER_NAME"]
eks_role_arn = os.environ["EKS_ROLE_ARN"]
cert_manager_yaml_url = os.environ["CERT_MANAGER_YAML_URL"]
alb_controller_yaml_url = os.environ["ALB_CONTROLLER_YAML_URL"]
ingclass_yaml_url = os.environ["INGCLASS_YAM_URL"]
eks = boto3.client('eks')
cluster_cache = {}


def get_cluster_info():
    # Get cluster endpoint and certificate
    cluster_info = eks.describe_cluster(name=cluster_name)
    endpoint = cluster_info['cluster']['endpoint']
    cert_authority = cluster_info['cluster']['certificateAuthority']['data']
    cluster_info = {
        "endpoint": endpoint,
        "ca": cert_authority
    }
    return cluster_info


def get_bearer_token():
    # Get Token
    signer = RequestSigner(
        service_id,
        session.region_name,
        'sts',
        'v4',
        session.get_credentials(),
        session.events
    )

    params = {
        'method': 'GET',
        'url': 'https://sts.{}.amazonaws.com/'
               '?Action=GetCallerIdentity&Version=2011-06-15'.format(session.region_name),
        'body': {},
        'headers': {
            'x-k8s-aws-id': cluster_name
        },
        'context': {}
    }

    signed_url = signer.generate_presigned_url(
        params,
        region_name=session.region_name,
        expires_in=STS_TOKEN_EXPIRES_IN,
        operation_name=''
    )
    base64_url = base64.urlsafe_b64encode(signed_url.encode('utf-8')).decode('utf-8')

    # remove any base64 encoding padding:
    return 'k8s-aws-v1.' + re.sub(r'=*', '', base64_url)


def lambda_handler(_event, _context):

    if cluster_name in cluster_cache:
        cluster = cluster_cache[cluster_name]
    else:
        # not present in cache retrieve cluster info from EKS service
        cluster = get_cluster_info()
        # store in cache for execution environment
        cluster_cache[cluster_name] = cluster
    # Create kubeconfig
    kubeconfig = {
        'apiVersion': 'v1',
        'clusters': [{
            'name': 'cluster1',
            'cluster': {
                'certificate-authority-data': cluster["ca"],
                'server': cluster["endpoint"]}
        }],
        'contexts': [{'name': 'context1', 'context': {'cluster': 'cluster1', "user": "user1"}}],
        'current-context': 'context1',
        'kind': 'Config',
        'preferences': {},
        'users': [{'name': 'user1', "user": {'token': get_bearer_token()}}]
    }
    # Manifest of ALB Controller K8S Service Account
    albControllerSa = {'apiVersion': 'v1',
                         'kind': 'ServiceAccount',
                         'metadata': {'annotations': {'eks.amazonaws.com/role-arn': eks_role_arn},
                                      'labels': {'app.kubernetes.io/component': 'controller',
                                                 'app.kubernetes.io/name': 'aws-load-balancer-controller'},
                                      'name': 'aws-load-balancer-controller',
                                      'namespace': 'kube-system'}}
    config.load_kube_config_from_dict(config_dict=kubeconfig)

    # Create K8S Service Account (Step 2 in the official doc listed at top)
    k8s_client = client.ApiClient()
    try:
        utils.create_from_dict(k8s_client, albControllerSa)
        print('K8S Service Account for ALB Controller is Deployed')
    except Exception as e:
        print('Fail Deploy K8S Service Account for ALB Controller: ')
        print(e)
    print('*************************')
    print('Install Cert-manager')
    # Install AWS LB Controller (Step 5 in official doc listed at top) :
    # a. Install cert-manager
    cm_yaml_generator = yaml.safe_load_all(requests.get(cert_manager_yaml_url).content.decode("utf-8"))
    for x in list(cm_yaml_generator):
        print('Deploying ' + x["kind"] + ":" + x["metadata"]["name"])
        try:
            utils.create_from_dict(k8s_client, x)
        except Exception as e:
            print('Deploy Failed!!' + x["kind"])
            print(e)
    # Wait 15 sec for Cert-Manager Pods to come up
    time.sleep(25)
    print('*************************')
    print('Install controller')
    # b. Install the controller
    alb_yaml_generator = yaml.safe_load_all(requests.get(alb_controller_yaml_url).content.decode("utf-8"))
    custom_objects_api = client.CustomObjectsApi()
    for y in list(alb_yaml_generator):
        if y['kind'] == "ServiceAccount":
            print(y['kind'] + " section is found! Skipping it")  # Service account has been created in step 2 already
        elif y['kind'] == "Deployment":
            print(y['kind'] + " section is found! Replacing your-cluster-name and deploy")
            y['spec']['template']['spec']['containers'][0]['args'][0] = '--cluster-name=' + cluster_name
            utils.create_from_dict(k8s_client, y)
        elif y['apiVersion'] == 'cert-manager.io/v1':
            group = "cert-manager.io"
            version = "v1"
            ns = y['metadata']['namespace']
            plural_name = ""
            # You can check plural name by "kubectl get crd", output is <plural_name>.<group name>
            if y['kind'] == "Certificate":
                plural_name = 'certificates'
            elif y['kind'] == "Issuer":
                plural_name = 'issuers'
            else:
                print("Cert Manager object creation Error, Found 'kind' other than Certificate and Issuer ")
            print('Deploying ' + y["kind"] + ":" + y["metadata"]["name"] + " Custom Object, plural name:" + plural_name)
            custom_objects_api.create_namespaced_custom_object(group, version, ns, plural_name, y)
        else:
            print('Deploying ' + y["kind"] + ":" + y["metadata"]["name"])
            utils.create_from_dict(k8s_client, y)

    # Deploy IngressClass and IngressClassParams
    ingress_yaml_generator = yaml.safe_load_all(requests.get(ingclass_yaml_url).content.decode("utf-8"))
    for z in list(ingress_yaml_generator):
        if z['apiVersion'] == 'elbv2.k8s.aws/v1beta1':
            group = "elbv2.k8s.aws"
            version = "v1beta1"
            print('Deploying cluster custom object: ' + z["kind"])
            custom_objects_api.create_cluster_custom_object(group, version, "ingressclassparams", z)
        else:
            print('Deploying ' + z["kind"])
            try:
                utils.create_from_dict(k8s_client, z)
            except:
                print('Deploy Failed!!' + z["kind"] )
    print("**** All Deployments are complete!! Checking deployment status... ****")
    # Verify the controller is installed
    appV1_api = client.AppsV1Api()
    resp_s = appV1_api.read_namespaced_deployment(name='aws-load-balancer-controller', namespace='kube-system').status
    print("aws-load-balancer-controller deployment status: ")
    print("  Available_replicas: " + str(resp_s.available_replicas))
    print("  Deployment Conditions: ")
    print("     type: " + str(resp_s.conditions[0].type) + ", status: " + str(resp_s.conditions[0].status))


