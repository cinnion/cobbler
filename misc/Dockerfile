FROM centos:latest

LABEL maintainer="Douglas Needham <cinnion@gmail.com>"
LABEL version="0.9"
LABEL description="This is a container designed to do cobbler builds for Jenkins."

# Update the image with things we need
RUN yum -y update ; \
    yum install -y epel-release ; \
    yum makecache fast && \
    yum install -y git openssl python-devel pyflakes redhat-rpm-config make mock rpm-build rpmdevtools rpmlint createrepo ; \
    yum clean all

# Copy in local createrepo wrapper, which handles linkages between a noarch
# architecture and the others, and actually runs the createrepo command.
COPY createrepo2 /usr/local/bin/

# Supply user/group so that rpmbuild < 4.14.2 does not blowup with "error: Bad owner/group"
# https://github.com/rpm-software-management/rpm/issues/2
RUN groupadd -g 48 apache ; \
    useradd -u 48 -g 48 --home-dir /usr/share/httpd apache ; \
    groupadd -g 500 jenkins ; \
    useradd -u 500 -g 500 --home-dir /var/lib/jenkins jenkins ; \
    echo "%dist .ka8zrt.el7" > /var/lib/jenkins/.rpmmacros

CMD ["sleep", "infinity"]
