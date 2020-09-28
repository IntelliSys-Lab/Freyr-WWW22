#! /bin/bash

if [ -z "$(echo $PATH | grep "/home/ubuntu/openwhisk/bin")" ]
then
    echo "" >> ~/.bashrc
    echo "# Configure wsk cli" >> ~/.bashrc
    echo "export PATH=$PATH:'/home/ubuntu/openwhisk/bin'" >> ~/.bashrc
    echo "" >> ~/.bashrc

    source ~/.bashrc
fi
