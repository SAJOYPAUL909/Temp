
import boto3
from botocore.exceptions import ClientError

AWS_ACCESS_KEY = "YOUR_ACCESS_KEY"
AWS_SECRET_KEY = "YOUR_SECRET_KEY"
AWS_REGION = "ap-south-1"

try:
    session = boto3.Session(
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION
    )

    ecr = session.client("ecr")

    response = ecr.get_paginator(
        "describe_repositories"
    )

    print("\nAWS ECR Repositories")
    print("-" * 60)

    count = 0

    for page in response.paginate():
        for repo in page["repositories"]:
            count += 1

            print(f"\nRepository: {repo['repositoryName']}")
            print(f"URI: {repo['repositoryUri']}")
            print(f"ARN: {repo['repositoryArn']}")
            print(f"Created: {repo['createdAt']}")
            print(f"Tag Mutability: {repo.get('imageTagMutability')}")
            print(f"Encryption: {repo.get('encryptionConfiguration')}")

    print("\n" + "-" * 60)
    print("Total repositories:", count)

except ClientError as e:
    print("AWS Error:", e.response["Error"]["Message"])

except Exception as e:
    print("Error:", str(e))
