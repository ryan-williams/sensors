# sensors

Scratch repo with work I've done to monitor the temperature and humidity in my apartment: https://boodoir.runsascoded.com

[![](https://cl.ly/77642052ea2c/Screen%20Shot%202018-11-21%20at%202.14.24%20PM.png)](https://boodoir.runsascoded.com)

The sawteeth are where the heater turned on / ran. Can you see where someone took a shower? 😂

## Background

Most people don't understand that warmer air is less humid, even if it has the same amount of water in it; warmer air can hold more water, so it is "thirstier", and more prone to stealing water from e.g. your skin.

This shook me a few years ago: heated indoor spaces during an NYC winter are often extremely dry (≈10% humidity) though the cold outside air is reasonably humid (≈40%); I visited Miami and realized I felt much better in 60-80% humidity that exists year-round there, and began humidifying my apartment.

On [the wirecutter's recommendation](https://thewirecutter.com/reviews/the-best-humidifier/), I bought 1, then 2, then 4 small-ish [Honeywell HCM350W humidifiers](https://www.amazon.com/dp/B002QAYJPO), before realizing I needed something heavier and adding an [Aircare MA1201](https://www.amazon.com/gp/product/B004S34ISA). I've run all 5 through 2 NYC winters and generally kept my apt at 50-60% humidity, ≈40% higher than it would have been otherwise, and noticeably more comfortable.

### Sensors

While determining whether my humidifiers were having an impact, I experimented with several humidity sensors.

#### SensorPush

I used 4 [SensorPush](https://www.amazon.com/gp/product/B01AEQ9X9I) sensors one winter, but they required proactively pulling data with my phone via Bluetooth. I bought [their $100 wifi bridge](https://www.amazon.com/gp/product/B01N17RWWV) and that improved the UX, but it refused to switch to a new wifi router when my apt did. The sensors have unreplaceable batteries, meaning 4x$50 for new ones every 6mos or so, which felt predatory; monitoring each one's battery and replacing individually was also annoying.

#### EngBird

I briefly used [this "InkBird" model](https://www.amazon.com/gp/product/B01G8H6KHA) that runs on a CR2032 "coin cell" battery, which was nice at ≈half the price, and with a cheap, replaceable battery. However again, pulling from phone over bluetooth manually is very painful and finicky, and the batteries had to be replaced about every month, so I quickly gave up on them.

#### Homebrewed

I decided I would make my own sensors that:

- run on USB power
- report data automatically+constantly
  - over wifi
  - to nice dashboards "in the cloud"

## Hardware

The basic setup for one sensor is currently:
- [Raspberry Pi Zero W](https://www.adafruit.com/product/3708) ([plus case](https://www.adafruit.com/product/3252))
- [HTU21D humidity sensor](https://www.adafruit.com/product/3515)
- [16GB micro SD card](https://www.amazon.com/gp/product/B013TMN4GW)

This runs about $50 (like a SensorPush), but should run forever and provide a better analytics UX.

A [Pi 3 B](https://www.adafruit.com/product/3055) also runs [InfluxDB] collecting metrics from the sensors and a [Grafana] server serving dashboards.

## Software

A "temps" service runs [`read.py`](./read.py) on each sensor, with one thread polling temperature+humidity data each second, and another sending them to InfluxDB (buffering and retrying as necessary).

### Sensor setup

Below are some steps I use to initialize a new sensor:

<details><summary><b>0. set env vars</b></summary><p>

These env vars will be used at various points:

- `RPI`: new rpi hostname / ssh alias
- `RPI_IP`: local WLAN IP of the new rpi, once its booted + connected to wifi (see step **2.**)
- `SSH_PUBKEY`: basename (within `~/.ssh`) of ssh public key
- `SSID`: wifi ssid
- `PSWD`: wifi password
- `DEVICE`: alias for device in influx db

</p></details>

<details><summary><b>1. set up OS image on SD card (laptop)</b></summary><p>

- [Download + unzip raspbian `.zip`](https://www.raspberrypi.org/downloads/raspbian/); I've been using "RASPBIAN STRETCH WITH DESKTOP AND RECOMMENDED SOFTWARE" but will try "RASPBIAN STRETCH LITE" next
- Burn unzipped `.img` onto SD card; I've used [Etcher](https://www.balena.io/etcher/) for OSX
- Configure SSH, wifi (2.4GHz networks only, for Pi Zero W!), and I2C and UART interfaces:

  ```bash

  cd /Volumes/boot

  # enable sshd on boot
  touch ssh

  SSID= # your wifi SSID; 2.4GHz only!
   PSWD= # your wifi password

  # enable uart, i2c interfaces
  cat >> config.txt <<EOF
  dtparam=i2c_arm=on
  enable_uart=1
  EOF

  # configure wifi
  cat > wpa_supplicant.conf <<EOF
  country=US
  ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
  update_config=1

  network={
      ssid="$SSID"
      psk="$PSWD"
      key_mgmt=WPA-PSK
  }
  EOF
  ```

</p></details>

<details><summary><b>2. power on raspberry pi; set <code>$RPI_IP</code> to local WLAN IP address</b></summary><p>

Once it's booted:
- find its IP address and store it in `$RPI_IP` for what follows.
  - (you can get this from e.g. your wifi router (which it will connect to on boot), or via a serial interface)
- also set `$RPI`: a hostname/alias you will address this RPi as

</p></details>

<details><summary><b>3. configure passwordless SSH, `temps.service` (laptop)</b></summary><p>

```bash
# create ssh alias
cat >> ~/.ssh/config <<EOF

Host $RPI
User pi
HostName $RPI_IP
EOF

# enable passwordless ssh; only two times you'll have to enter the default password ("raspberry")
scp ~/.ssh/$SSH_PUBKEY $RPI:
ssh $RPI 'mkdir .ssh && cat $SSH_PUBKEY >> .ssh/authorized_keys'

# (passwordless!) copy over source file from this repo
scp read.py $RPI:

# set hostname
ssh $RPI "sudo echo $RPI > /etc/hostname"

# passwordless!
ssh $RPI
```

</p></details>

<details><summary><b>4. configure rpi</b></summary><p>

```bash
# set new password for 'pi' user
passwd

# remove obsolete local hostname alias
sudo perl -pi -e "s/raspberrypi/$HOSTNAME/" /etc/hosts

sudo apt-get install i2c-tools
sudo echo i2c-dev >> /etc/modules

# install necessary python deps
sudo pip3 install RPi.GPIO adafruit-circuitpython-HTU21D adafruit-circuitpython-si7021 influxdb pytz

# optional: useful cruft removal
sudo apt-get purge wolfram-engine libreoffice* scratch minecraft-pi sonic-pi dillo gpicview oracle-java8-jdk openjdk-7-jre oracle-java7-jdk openjdk-8-jre
sudo apt-get clean
sudo apt-get autoremove

# set this var to be the device you want to report metrics to InfluxDB as
DEVICE=$HOSTNAME

# write "temps.service" file
sudo bash -c "cat >/lib/systemd/system/temps.service" <<EOF
[Unit]
Description=Temp/Humidity Reporter
After=multi-user.target

[Service]
Type=idle
ExecStart=/usr/bin/python3 -u /home/pi/read.py -d $DEVICE

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable temps

# start the temps service!
sudo systemctl start temps

# check its status a few times; readings may take a few seconds to start flowing
sudo systemctl status temps

# all done! log out
exit
```

</p></details>

### Server setup

<details><summary><b>InfluxDB</b></summary><p>

…is easily installed via APT:

```bash
sudo apt-get install influxdb
```

</p></details>

<details><summary><b>Grafana</b></summary><p>
  
…is [a little trickier](https://grafana.com/grafana/download?platform=arm):

```bash
wget https://s3-us-west-2.amazonaws.com/grafana-releases/release/grafana_5.3.4_armhf.deb 
sudo dpkg -i grafana_5.3.4_armhf.deb
```

*The version you get from a vanilla `sudo apt-get install grafana` is really old! Don't try to use it!*

#### Enable anonymous access

In `/etc/grafana/grafana.ini`:

```
[auth.anonymous]
# enable anonymous access
;enabled = true

# specify organization name that should be used for unauthenticated users
;org_name = <some org name>

# specify role for unauthenticated users
;org_role = Viewer
```

## Roadmap

[The issue tracker](https://github.com/ryan-williams/sensors/issues) points to a lot of future work.


[InfluxDB]: https://github.com/influxdata/influxdb
[Grafana]: https://grafana.com/
