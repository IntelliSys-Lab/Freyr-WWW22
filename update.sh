#! /bin/bash

git pull
./gradlew distDocker
./clear_dangling_images.sh