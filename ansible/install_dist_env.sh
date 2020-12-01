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
#sudo ./gradlew releaseBinaries -PnativeBuild
#mkdir ../openwhisk/bin
#cp build/wsk ../openwhisk/bin
#cd ../openwhisk/ansible

#
#  Export wsk folder to system path if not detected
#

# if [ -z "$(echo $PATH | grep "/home/ubuntu/openwhisk/bin")" ]
# then
#     echo "" >> ~/.bashrc
#     echo "# Configure wsk cli" >> ~/.bashrc
#     echo "export PATH=$PATH:'/home/ubuntu/openwhisk/bin'" >> ~/.bashrc
#     echo "alias wsk='wsk -i'" >> ~/.bashrc
#     echo "" >> ~/.bashrc
# fi

#
# Export ServerlessBench home directory
#

# if [ -z "$(env | grep "SERVERLESSBENCH_HOME")" ]
# then
#     echo "" >> ~/.bashrc
#     echo "# Export ServerlessBench" >> ~/.bashrc
#     echo "export SERVERLESSBENCH_HOME='/home/ubuntu/ServerlessBench/Testcase4-Application-breakdown'" >> ~/.bashrc
#     echo "" >> ~/.bashrc
# fi

# source ~/.bashrc

#
# Build docker images on bootstrapper (may not be necessary)
#

#cd ../ && sudo ./gradlew distDocker
#cd ansible

#
# Install prerequisites of distributed cluster for openwhisk
#

sudo ansible all -i environments/distributed -m ping
sudo ansible-playbook -i environments/distributed update.yml 
sudo ansible-playbook -i environments/distributed setup.yml
#sudo ansible-playbook -i environments/distributed prereq.yml 

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
#sudo ansible-playbook -i environments/distributed invoker.yml -e docker_image_tag=invoker_idle_1min

#
# Configure wsk cli
#

wsk property set --auth $(cat files/auth.guest) --apihost https://$(cat environments/distributed/hosts | grep -A 1 "\[edge\]" | grep ansible_host | awk {'print $1'}):443 

#
# Test wsk cli
#

wsk list -vi
wsk property get -i

