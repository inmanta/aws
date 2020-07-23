pipeline {
  agent any
  triggers{
    cron(BRANCH_NAME == "master" ? "H H(2-5) * * *": "")
  }
  options { disableConcurrentBuilds() }
  environment {
    PIP_INDEX_URL='https://artifacts.internal.inmanta.com/inmanta/dev'
    PIP_PRE="true"
    PYTEST_INMANTA_DEV="true"
    AWS_REGION="eu-west-1"
  }
  stages {
    stage("setup"){
      steps{
        script{
          sh'''
          python3 -m venv ${WORKSPACE}/env
          ${WORKSPACE}/env/bin/pip install -U pip
          ${WORKSPACE}/env/bin/pip install -r requirements.txt
          ${WORKSPACE}/env/bin/pip install -r requirements.dev.txt
          '''
        }
      }
    }
    stage("tests"){
      steps{
        withCredentials([usernamePassword(
            credentialsId: "aws-jenkins-user",
            usernameVariable: "AWS_ACCESS_KEY_ID",
            passwordVariable: "AWS_SECRET_ACCESS_KEY"
          )]){
          sh'''
          ${WORKSPACE}/env/bin/pytest tests -v --junitxml=junit.xml
          '''
          junit 'junit.xml'
        }
      }
    }
    stage("code linting"){
      steps{
        script{
          sh'''
          ${WORKSPACE}/env/bin/flake8 plugins tests
          '''
        }
      }
    }
  }
}
