# What problem does ecs-daemon-protector solve?

When ecs instance set DRAINING, all tasks on the instance accept SIGTERM and will be stopped. If you run a log-router(such as fluentd) as DAEMON service, you hope to stop the log-router at last. But now, ECS cannot control order of termination for REPLICA and DAEMON. 

- https://github.com/aws/containers-roadmap/issues/128

`ecs-daemon-protector` run as sidecar of your DAEMON container, and protect the container from termination until all REPLICA tasks stopped.


# How to use?

## Build and push your repository

```SHELL
$(aws ecr get-login --no-include-email --region [YOUR_DEFAULT_REGION])
ECR_REPO=[YOUR_AWS_ACCOUNT_ID].dkr.ecr.ap-northeast-1.amazonaws.com
IMAGE_NAME=ecs-daemon-protector
docker build . 
docker push ${ECR_REPO}/${IMAGE_NAME}:latest
```

## Create task role for daemon-protector

Prepare task role with the following permissions.

```JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECSReadOnly",
      "Effect": "Allow",
      "Action": [
        "ecs:List*",
        "ecs:Describe*"
      ],
      "Resource": "*"
    }
  ]
}
```

## Configure dependsOn in your container definition

https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_ContainerDefinition.html

```JSON
[
  {
    "name": "my-daemon-app",
    "image": "my-daemon-app:latest",
    "essential": true
  },
  {
    "name": "ecs-daemon-protector",
    "image": "YOUR_AWS_ACCOUNT_ID.dkr.ecr.YOUR_REGION_NAME.amazonaws.com/ecs_daemon_protector:latest",
    "dependsOn": [
      {
        "containerName": "my-daemon-app",
        "condition": "START"
      }
    ]
  }
]
```

- `dependsOn` could define order to container start and stop. In this sample, when ecs instance is draining, `my-daemon-app` cannot exit until `ecs-daemon-protector` exit.
- `ecs-daemon-protector` monitor that all tasks excepted daemon services are stopped. And after those tasks exit, `ecs-daemon-protector` goes to exit.
    - So, daemon services will be protected from early exit.
