
import boto3
from botocore.exceptions import ClientError, BotoCoreError

AWS_ACCESS_KEY = "YOUR_ACCESS_KEY"
AWS_SECRET_KEY = "YOUR_SECRET_ACCESS_KEY"
AWS_REGION = "ap-south-1"

try:
    session = boto3.Session(
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION
    )

    # Test AWS authentication
    sts = session.client("sts")
    identity = sts.get_caller_identity()

    print("AWS Connection Successful!")
    print("Account ID:", identity["Account"])
    print("User ARN:", identity["Arn"])
    print("User ID:", identity["UserId"])

    # Test EC2 access
    ec2 = session.client("ec2")
    response = ec2.describe_instances(MaxResults=5)

    print("\nEC2 Access Successful!")
    print("Connection to EC2 service verified.")

except ClientError as e:
    print("AWS API Error:", e.response["Error"]["Message"])

except BotoCoreError as e:
    print("AWS Connection Error:", str(e))

except Exception as e:
    print("Unexpected Error:", str(e))
