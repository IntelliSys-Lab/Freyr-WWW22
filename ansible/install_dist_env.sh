#! /bin/bash

# 
# Install prerequisites for bootstapper
#

#cd ../tools/ubuntu-setup/ && ./all.sh
#cd ../../ansible

#
# Install wsk cli for bootstrapper
#

#cd ../../ && git clone https://github.com/apache/openwhisk-cli.git
#cd openwhisk-cli
#git checkout 23b5790
#sudo ./gradlew releaseBinaries -PnativeBuild
#cd ./build && sudo ln -s $(pwd)/wsk /usr/local/bin/wsk
#cd ../../openwhisk/ansible

#
# Build docker images on bootstrapper (may be unnecessary)
#

#cd ../ && sudo ./gradlew distDocker
#cd ansible

#
# Download workloads
#

#cd /home/ubuntu
#git clone https://github.com/hanfeiyu/SAAF.git

#
# Download Azure Function trances
#

#cd /home/ubuntu/openwhisk/agent && ./install_prereq.sh
#cd /home/ubuntu/openwhisk/ansible

#
# Install prerequisites of distributed cluster for openwhisk
#

sudo ansible all -i environments/distributed -m ping
sudo ansible-playbook -i environments/distributed update.yml 
sudo ansible-playbook -i environments/distributed setup.yml

#
# Boot openwhisk cluster
#

sudo ansible-playbook -i environments/distributed couchdb.yml
sudo ansible-playbook -i environments/distributed initdb.yml
sudo ansible-playbook -i environments/distributed wipe.yml
sudo ansible-playbook -i environments/distributed openwhisk.yml
sudo ansible-playbook -i environments/distributed postdeploy.yml
sudo ansible-playbook -i environments/distributed apigateway.yml
sudo ansible-playbook -i environments/distributed routemgmt.yml
sudo ansible-playbook -i environments/distributed login_docker_hub.yml

#
# Configure wsk cli
#

wsk property set --auth $(cat files/auth.guest) --apihost https://$(cat environments/distributed/hosts | grep -A 1 "\[edge\]" | grep ansible_host | awk {'print $1'}):443 

#
# Test wsk cli
#

wsk list -vi
wsk property get -i

#
# Deploy functions
#

cd ../agent
./deploy_functions.sh
# ./deploy_test.sh

# List functions
wsk -i action list
