# abhaile
Home Server configs

## commands.txt
apt install crun vim git vlan curl systemd-resolved

modprobe 8021q
echo "8021q" >> /etc/modules

mv /etc/network/interfaces /etc/network/interfaces.save
systemctl enable systemd-networkd
mv network/* /etc/systemd/network/

systemctl enable systemd-resolved
ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf