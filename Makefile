.ONESHELL:
SHELL = /bin/bash

STACK_NAME = glue-interactive-session-control
AWS_REGION = "eu-west-1"
NOTIFICATION_EMAIL_ADDRESS = "foo.bar@provider.com"
ENFORCE_VPC_CONNECTION = "false"
MAX_WORKERS = "15"
MAX_IDLE_TIMEOUT_MINUTES = "300"
KILL_SESSION = "False"


pre-flight-checks:
	@echo "Check aws-cli present"
	aws --version || (echo "aws cli not present"; exit 1)
	@echo "Check SAM present"
	sam --version || (echo "SAM cli not present"; exit 1)
	@echo "Check AWS credentials are set and ready"
	aws sts get-caller-identity || (echo "AWS credentials expired $$?"; exit 1)

install-pre-requisites: pre-flight-checks
	python3 -m venv .venv
	. .venv/bin/activate
	pip3 install -U pip
	pip install -r requirements.txt

build: pre-flight-checks
	. .venv/bin/activate
	python -m pytest
	sam build -t cfn/template.yaml

deploy: build
	. .venv/bin/activate
	sam validate --region ${AWS_REGION} -t cfn/template.yaml
	sam deploy \
		--capabilities CAPABILITY_AUTO_EXPAND CAPABILITY_IAM \
		--stack-name ${STACK_NAME} \
		--resolve-s3 \
		--region ${AWS_REGION} \
		--parameter-overrides ParameterKey=NotificationEmailAddress,ParameterValue=${NOTIFICATION_EMAIL_ADDRESS} ParameterKey=EnforceVPCConnection,ParameterValue=${ENFORCE_VPC_CONNECTION} ParameterKey=MaxWorkers,ParameterValue=${MAX_WORKERS} ParameterKey=MaxIdleTimeoutMinutes,ParameterValue=${MAX_IDLE_TIMEOUT_MINUTES} ParameterKey=KillSession,ParameterValue=${KILL_SESSION}

clean-up:
	. .venv/bin/activate
	sam delete --stack-name ${STACK_NAME} --region ${AWS_REGION}
