#!/usr/bin/env groovy

pipeline {
    // REPO_BASE_DIR not used here, since regardless of ordering between the
    // agent and environment blocks we fall afoul of JENKINS-43911. :(
    agent {
        docker {
            image 'ka8zrt-centos-builds'
            registryUrl 'https://registry.ka8zrt.com'
            args "-v /repos/local/centos/7:/repos/local/centos/7:rw,z"
        }
    }

    environment {
        REPO_BASE_DIR = '/repos/local/centos/7'
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '5'))
        disableConcurrentBuilds()
    }

    stages {
        stage('Container prep') {
            steps {
                sh '''
                    groupadd -g 48 apache
                    useradd -u 48 -g 48 --home-dir /usr/share/httpd apache

                    yum install -y git openssl python-devel pyflakes redhat-rpm-config make mock rpm-build rpmdevtools rpmlint createrepo
                '''
            }
        }

        stage('Build') {
            steps {
                sh 'make rpms'
            }
        }
    }

    post {
        success {
            sh '''
                rm -rf ${REPO_BASE_DIR}/noarch/Packages/{cobbler,cobbler-web,koan}-*
                cp -p rpm-build/{cobbler,cobbler-web,koan}-[0-9]*.noarch.rpm ${REPO_BASE_DIR}/noarch/Packages/
                cp -p rpm-build/*.src.rpm ${REPO_BASE_DIR}/Sources/SPackages/
                /usr/local/bin/createrepo2 ${REPO_BASE_DIR}
                rpm -q -i -p rpm-build/{cobbler,cobbler-web,koan}-[0-9]*.noarch.rpm
                rpm -q -i -p rpm-build/*.src.rpm
            '''
        }
    }
}
