## EKS Single Button AWS Load Balancer Controller Installation

To deploy AWS Load Balancer Controller on existing EKS clusters requires multiple [manual steps](https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html), and it is hard to manage at scale. This solution automates the manual deployment aspects of AWS Load Balancer Controller for existing EKS clusters.

## Solution Overview

This AWS CloudFormation solution automates the manual deployment aspects of AWS Load Balancer Controller for an existing EKS cluster. The manual steps include: creating an AWS Identity and Access Management (IAM) policy to allow AWS Load Balancer Controller to make AWS API calls creating a Kubernetes service account and attaching the IAM policy and associated role to the service account, configuring the AWS Security Token Service endpoint type used by your Kubernetes service account, installing AWS Load Balancer controller by applying a Kubernetes manifest and cert-manager, and verifying the installation.

The Solution automates all the preceding manual steps. The solution's CloudFormation template creates an IAM policy for the AWS Load Balancer Controller that allows it to make calls to AWS APIs by using assume-role.

- It creates an IAM role with your provided OpenID Connect (OIDC) ID as the parameter and creates a trust policy and IAM role.
- It also creates an AWS Lambda function that creates a Kubernetes service account named aws-load-balancer-controller annotated with the IAM role.
- The Lambda function deploys cert-manager and AWS Load Balancer Controller by applying the default yaml files provided in the [official document](https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html) to the EKS cluster.
  
To grant the Amazon EKS API access to the Lambda function, you can follow this [Amazon post](https://aws.amazon.com/blogs/opensource/simplifying-kubernetes-configurations-using-aws-lambda/) to learn how to create a Lambda IAM Role and authorize the Lambda role to administer the EKS cluster.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

