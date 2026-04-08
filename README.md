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
export IMAGE_TAG=$(git rev-parse --short HEAD)

aws ecr get-login-password --region us-east-1 --profile welkin-cicd | docker login --username AWS --password-stdin 673402552655.dkr.ecr.us-east-1.amazonaws.com

docker build --platform linux/arm64 --provenance=false -f Dockerfile.lambda -t 673402552655.dkr.ecr.us-east-1.amazonaws.com/welikan-webhooks-handler:$IMAGE_TAG .
docker push 673402552655.dkr.ecr.us-east-1.amazonaws.com/welikan-webhooks-handler:$IMAGE_TAG
```

Deploy via terragrunt:

```bash
cd /path/to/terragrunt/aws/v8/stg/us-east-1/lambda/webhooks-handler
IMAGE_TAG=<image-tag> terragrunt apply
```
