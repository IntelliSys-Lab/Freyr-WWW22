#! /bin/bash

wsk="wsk -i"

#
# alu
#

cd ../../SAAF/python_alu/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cd ./build
zip -X -r ./index.zip *

for memory in $(seq 1 64)
do
    $wsk action update alu$memory --kind python:3 --main main_alu --memory $memory index.zip
done

cd ../../../../openwhisk/LambdaRM

#
# ms
#

cd ../../SAAF/python_merge_sort/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cd ./build
zip -X -r ./index.zip *

for memory in $(seq 1 64)
do
    $wsk action update ms$memory --kind python:3 --main main_ms --memory $memory index.zip
done

cd ../../../../openwhisk/LambdaRM

#
# gd
#

cd ../../SAAF/python_gradient_descend/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for memory in $(seq 1 64)
do
    $wsk action update gd$memory --kind python:3 --main main_gd --memory $memory index.zip
done

cd ../../../../openwhisk/LambdaRM

#
# knn
#

cd ../../SAAF/python_k_nearest_neighbor/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for memory in $(seq 1 64)
do
    $wsk action update knn$memory --kind python:3 --main main_knn --memory $memory index.zip
done

cd ../../../../openwhisk/LambdaRM

#
# image process sequence
#

cd ../../ServerlessBench/Testcase4-Application-breakdown
./deploy.sh --image-process
cd ../../openwhisk/LambdaRM

