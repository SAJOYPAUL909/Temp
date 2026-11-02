import boto3
from botocore.exceptions import ClientError

# Replace these with your actual AWS credentials and region,
# or retrieve them from AWS Secrets Manager if required.
AWS_ACCESS_KEY_ID = "YOUR_AWS_ACCESS_KEY_ID"
AWS_SECRET_ACCESS_KEY = "YOUR_AWS_SECRET_ACCESS_KEY"
AWS_REGION = "us-east-1"  # Change to your target region


def get_aws_session():
  """Creates a Boto3 session using provided access and secret keys."""
  return boto3.Session(
      aws_access_key_id=AWS_ACCESS_KEY_ID,
      aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
      region_name=AWS_REGION,
  )


def list_subnets(ec2_client):
  print("\n--- Subnets ---")
  try:
    response = ec2_client.describe_subnets()
    for subnet in response.get("Subnets", []):
      print(
          f"Subnet ID: {subnet['SubnetId']} | CIDR: {subnet['CidrBlock']} |"
          f" VPC ID: {subnet['VpcId']}"
      )
  except ClientError as e:
    print(f"Error listing subnets: {e}")


def list_security_groups(ec2_client):
  print("\n--- Security Groups ---")
  try:
    response = ec2_client.describe_security_groups()
    for sg in response.get("SecurityGroups", []):
      print(f"SG ID: {sg['GroupId']} | Name: {sg['GroupName']} | Description: {sg['Description']}")
  except ClientError as e:
    print(f"Error listing security groups: {e}")


def list_ecr_repositories(ecr_client):
  print("\n--- ECR Repositories ---")
  try:
    response = ecr_client.describe_repositories()
    for repo in response.get("repositories", []):
      print(f"Repo Name: {repo['repositoryName']} | URI: {repo['repositoryUri']}")
  except ClientError as e:
    print(f"Error listing ECR repositories: {e}")


def list_ecs_resources(ecs_client):
  print("\n--- ECS Clusters ---")
  try:
    clusters_response = ecs_client.list_clusters()
    cluster_arns = clusters_response.get("clusterArns", [])

    if not cluster_arns:
      print("No ECS clusters found.")
      return

    # Describe clusters for details
    cluster_details = ecs_client.describe_clusters(clusters=cluster_arns)
    for cluster in cluster_details.get("clusters", []):
      print(f"Cluster Name: {cluster['clusterName']} | Status: {cluster['status']}")

      # List services inside each cluster
      services_response = ecs_client.list_services(cluster=cluster["clusterArn"])
      service_arns = services_response.get("serviceArns", [])
      if service_arns:
        print(f"  Services in {cluster['clusterName']}:")
        for s_arn in service_arns:
          print(f"    - {s_arn.split('/')[-1]}")
      else:
        print(f"  No services running in {cluster['clusterName']}")

  except ClientError as e:
    print(f"Error listing ECS resources: {e}")


def main():
  session = get_aws_session()

  # Initialize clients
  ec2_client = session.client("ec2")
  ecr_client = session.client("ecr")
  ecs_client = session.client("ecs")

  print(f"Connected to AWS Region: {AWS_REGION}")

  list_subnets(ec2_client)
  list_security_groups(ec2_client)
  list_ecr_repositories(ecr_client)
  list_ecs_resources(ecs_client)


if __name__ == "__main__":
  main()
