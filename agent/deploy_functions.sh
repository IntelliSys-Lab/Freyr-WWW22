#! /bin/bash

echo ""
echo "Downloading SAAF Repo..."
echo ""

cd /home/ubuntu 

if [ ! -d "SAAF" ]
then
    git clone https://github.com/hanfeiyu/SAAF.git
fi

echo ""
echo "Deploying functions..."
echo ""

#
# dynamic-html (dh)
#

cd /home/ubuntu/SAAF/python_dynamic_html/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Install virtualenv
sudo docker run --rm -v "$PWD:/tmp" openwhisk/python3action bash \
  -c "cd tmp && virtualenv virtualenv && source virtualenv/bin/activate && pip3 install -r requirements.txt"

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update dh_$i --kind python:3 --main main --memory $i index.zip
done

#
# email-generation (eg)
#

cd /home/ubuntu/SAAF/python_email_generation/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Install virtualenv
sudo docker run --rm -v "$PWD:/tmp" openwhisk/python3action bash \
  -c "cd tmp && virtualenv virtualenv && source virtualenv/bin/activate && pip3 install -r requirements.txt"

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update eg_$i --kind python:3 --main main --memory $i index.zip
done

#
# image-processing (ip)
#

cd /home/ubuntu/SAAF/python_image_processing/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Install virtualenv
sudo docker run --rm -v "$PWD:/tmp" openwhisk/python3action bash \
  -c "cd tmp && virtualenv virtualenv && source virtualenv/bin/activate && pip3 install -r requirements.txt"

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update ip_$i --kind python:3 --main main --memory $i index.zip
done


#
# video-processing (vp)
#

cd /home/ubuntu/SAAF/python_video_processing/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Install virtualenv
sudo docker run --rm -v "$PWD:/tmp" openwhisk/python3action bash \
  -c "cd tmp && virtualenv virtualenv && source virtualenv/bin/activate && pip3 install -r requirements.txt"

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build

# Install non-pip dependency
wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -P "./build"
pushd "./build" > /dev/null
tar -xf ffmpeg-release-amd64-static.tar.xz
rm *.tar.xz
mv ffmpeg-* ffmpeg
popd > /dev/null

cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update vp_$i --kind python:3 --main main --memory $i index.zip
done


#
# image-recognition (ir)
#

cd /home/ubuntu/SAAF/python_image_recognition/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build

cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update ir_$i --docker your_username/actionloop-python-v3.6-ai --main main --memory $i index.zip
done


#
# k nearest neighbors (knn)
#

cd /home/ubuntu/SAAF/python_k_nearest_neighbors/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Install virtualenv
sudo docker run --rm -v "$PWD:/tmp" openwhisk/python3action bash \
  -c "cd tmp && virtualenv virtualenv && source virtualenv/bin/activate && pip3 install -r requirements.txt"

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update knn_$i --kind python:3 --main main --memory $i index.zip
done


#
# arithmetic-logic-unit (alu)
#

cd /home/ubuntu/SAAF/python_arithmetic_logic_unit/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Install virtualenv
sudo docker run --rm -v "$PWD:/tmp" openwhisk/python3action bash \
  -c "cd tmp && virtualenv virtualenv && source virtualenv/bin/activate && pip3 install -r requirements.txt"

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update alu_$i --kind python:3 --main main --memory $i index.zip
done


#
# merge-sorting (ms)
#

cd /home/ubuntu/SAAF/python_merge_sorting/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Install virtualenv
sudo docker run --rm -v "$PWD:/tmp" openwhisk/python3action bash \
  -c "cd tmp && virtualenv virtualenv && source virtualenv/bin/activate && pip3 install -r requirements.txt"

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update ms_$i --kind python:3 --main main --memory $i index.zip
done


#
# gradient-descent (gd)
#

cd /home/ubuntu/SAAF/python_gradient_descent/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Install virtualenv
sudo docker run --rm -v "$PWD:/tmp" openwhisk/python3action bash \
  -c "cd tmp && virtualenv virtualenv && source virtualenv/bin/activate && pip3 install -r requirements.txt"

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update gd_$i --kind python:3 --main main --memory $i index.zip
done


#
# dna-visualisation (dv)
#

cd /home/ubuntu/SAAF/python_dna_visualization/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Install virtualenv
sudo docker run --rm -v "$PWD:/tmp" openwhisk/python3action bash \
  -c "cd tmp && virtualenv virtualenv && source virtualenv/bin/activate && pip3 install -r requirements.txt"

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update dv_$i --kind python:3 --main main --memory $i index.zip
done


# #
# # Image process pipeline
# #
# cd /home/ubuntu/ServerlessBench/Testcase4-Application-breakdown
# ./deploy.sh --image-process

# #
# # Alexa skills
# #
# ./deploy.sh --alexa

#
# Initialize workload input in CouchDB
#

cd /home/ubuntu/openwhisk/agent
python3 init_workload_input.py

echo ""
echo "Finish deployment!"
echo ""
