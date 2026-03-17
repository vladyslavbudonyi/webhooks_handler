# WH handler
Simple project to manage webhooks

## Local development

```bash
make install
make run
```

## Lambda deployment

Build and push the Docker image to ECR:

```bash

aws ecr get-login-password --region us-east-1 --profile welkin-cicd | docker login --username AWS --password-stdin 673402552655.dkr.ecr.us-east-1.amazonaws.com

docker build --platform linux/arm64 --provenance=false -f Dockerfile.lambda -t 673402552655.dkr.ecr.us-east-1.amazonaws.com/welikan-webhooks-handler:latest .
docker push 673402552655.dkr.ecr.us-east-1.amazonaws.com/welikan-webhooks-handler:latest

```

After pushing, update the Lambda function:

```bash
aws lambda update-function-code \
  --function-name welikan-webhooks-handler \
  --image-uri $ECR_URL:latest \
  --region us-east-1
```
