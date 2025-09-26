# abhaile
Home Server configs

## Initial Setup
apt install sudo
usermod -aG sudo moonpie
echo 'moonpie  ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/user

sudo apt update && sudo apt upgrade -y
sudo apt install -y unattended-upgrades
echo unattended-upgrades unattended-upgrades/enable_auto_updates boolean true | sudo debconf-set-selections
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

apt install podman crun vim git vlan curl systemd-resolved lm-sensors

modprobe nct6683 force=on
modprobe 8021q
echo "8021q" >> /etc/modules

mv /etc/network/interfaces /etc/network/interfaces.save
systemctl enable systemd-networkd
mv network/* /etc/systemd/network/

systemctl enable systemd-resolved
ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf

## Coral TPU
wget https://packages.cloud.google.com/apt/doc/apt-key.gpg
gpg --no-default-keyring --keyring ./temp-keyring.gpg --import apt-key.gpg
gpg --no-default-keyring --keyring ./temp-keyring.gpg --export --output google-apt.gpg
rm apt-key.gpg temp-keyring.gpg
sudo mv google-apt.gpg /etc/apt/keyrings/
echo "deb [signed-by=/etc/apt/keyrings/google-apt.gpg] https://packages.cloud.google.com/apt coral-edgetpu-stable main" | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
cd ~/git/
git clone https://github.com/jnicolson/gasket-builder
cd gasket-builder/
sed -i 's#FROM ubuntu:24.04#FROM docker.io/library/debian:trixie#' Dockerfile
podman build --output . .
sudo apt-get update && sudo apt-get install ./gasket-dkms*.deb libedgetpu1-std
rm -f ./gasket-dkms*.deb
sudo sh -c "echo 'SUBSYSTEM==\"apex\", MODE=\"0660\", GROUP=\"apex\"' >> /etc/udev/rules.d/65-apex.rules"
sudo groupadd apex && sudo adduser $USER apex
sudo reboot

## Dynamic DNS
sudo apt install -y ddclient
systemctl enable ddclient.service
systemctl start ddclient.service

## Containers
systemctl enable --now netavark-dhcp-proxy.socket
mv podman/* /etc/containers/systemd/
systemctl daemon-reload

vim secret ... <omada_password>
printf "%s" "$(<secret)" | podman secret create core-dns-pw -
rm -f secret
