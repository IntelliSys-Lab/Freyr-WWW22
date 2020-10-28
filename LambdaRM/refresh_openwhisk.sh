#! /bin/bash

cd ../ansible 
sudo ansible-playbook -i environments/distributed openwhisk.yml
cd ../LambdaRM
