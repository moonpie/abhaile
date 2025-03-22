# abhaile
Home Server configs

## commands.txt
apt install podman crun vim git vlan curl systemd-resolved 

modprobe 8021q
echo "8021q" >> /etc/modules

mv /etc/network/interfaces /etc/network/interfaces.save
systemctl enable systemd-networkd
mv network/* /etc/systemd/network/

systemctl enable systemd-resolved
ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf

systemctl enable --now netavark-dhcp-proxy.socket
mv podman/* /etc/containers/systemd/
systemctl daemon-reload

vim secret ... <omada_password>
printf "%s" "$(<secret)" | podman secret create core-dns-pw -
rm -f secret