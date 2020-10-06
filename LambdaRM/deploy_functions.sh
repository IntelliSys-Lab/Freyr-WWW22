#! /bin/bash

# alu
cd ../../SAAF/python_alu/deploy
./publish.sh 0 0 0 0 1 1

# ms
cd ../../python_merge_sort/deploy
./publish.sh 0 0 0 0 1 1

# gd
cd ../../python_gradient_descend/deploy
./publish.sh 0 0 0 0 1 1

# knn
cd ../../python_k_nearest_neighbor/deploy
./publish.sh 0 0 0 0 1 1

# Image process sequence
cd ../../../ServerlessBench/Testcase4-Application-breakdown
./deploy.sh --image-process

# Alexa skills
./deploy.sh --alexa

cd ../../openwhisk/LambdaRM
