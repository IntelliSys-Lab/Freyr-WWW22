#! /bin/bash

docker_dangling_images=`sudo docker images | grep "none" | awk '{print $3}'`

if [ -n "$docker_dangling_images" ]
then
    echo ""
    echo "Remove dangling images"
    echo $docker_dangling_images | xargs sudo docker rmi
fi
