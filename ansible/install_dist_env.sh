#! /bin/bash

# 
# Install prerequisites for bootstapper
#

#cd ../tools/ubuntu-setup/ && ./all.sh
#cd ../../ansible
#chmod 600 openwhisk.pem

#
# Install wsk cli for bootstrapper
#

#cd ../../ && git clone https://github.com/apache/openwhisk-cli.git
#cd openwhisk-cli
#sudo ./gradlew releaseBinaries -PnativeBuild
#mkdir ../openwhisk/bin
#cp build/wsk ../openwhisk/bin
#cd ../openwhisk/ansible

#
# Alias wsk to .bashrc if no alias ever made before 
#

#if [ -z "$(cat ~/.bashrc | tail -n 3 | grep wsk)" ]
#then
#    echo "" >> ~/.bashrc
#    echo "# Configure wsk cli" >> ~/.bashrc
#    echo "alias wsk=\"/home/ubuntu/openwhisk/bin/wsk -i\"" >> ~/.bashrc
#    echo "" >> ~/.bashrc
#fi

#
# Install prerequisites of distributed cluster for openwhisk
#

sudo ansible all -i environments/distributed -m ping
sudo ansible-playbook -i environments/distributed setup.yml
sudo ansible-playbook -i environments/distributed prereq_build.yml 
#sudo ansible-playbook -i environments/distributed prereq.yml 

#
# Build docker images on bootstrapper (may not be necessary)
#

#cd ../ && sudo ./gradlew distDocker
#cd ansible

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

# Hot swap invoker with type of 1 min idle
sudo ansible-playbook -i environments/distributed invoker.yml -e docker_image_tag=invoker_idle_1min

#
# Configure wsk cli
#

../bin/wsk property set --auth $(cat files/auth.guest) --apihost https://$(cat environments/distributed/hosts | grep -A 1 "\[edge\]" | grep ansible_host | awk {'print $1'}):443 

#
# Test wsk cli
#

../bin/wsk list -vi
../bin/wsk property get -i

