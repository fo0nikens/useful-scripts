#! /usr/bin/env python

import sys, os, os.path
import time, datetime
from binascii import hexlify
import argparse, subprocess


#
# Simple script to make IPSec tunnel configurations for use with
# Linux/BSD 'setkey' utility
#
# Author: Sudhi Herle <sudhi@herle.net>
# Created on: June 13, 2005
# License: GPLv2
#

Z        = os.path.basename(sys.argv[0])
__doc__  = """%s helps create site-to-site VPN config with pre-shared random keys.""" % Z
Epilog   = """LOCAL and REMOTE specification is of the form:

    PublicIP:subnet1[,subnet2,subnet3...]

e.g.,
%s  55.66.77.88:192.168.5.0/24,192.168.10.0/24   100.100.200.200:172.16.0.0/16

The above invocation will setup a tunnel between the "local" subnets
192.168.5.0/24, 192.168.10.0/24  and the "remote" subnet 172.16.0.0/16.
This tunnel uses the local public IP of 55.66.77.88 and remote public IP of
100.100.200.200.
""" % Z


def warn(fmt, *args):
    s = "%s: %s" % (Z, fmt)
    if args:                 s  = s % args
    if not s.endswith('\n'): s += '\n'

    sys.stderr.write(s)
    sys.stderr.flush()

def die(fmt, *args):
    warn(fmt, *args)
    sys.exit(1)

def randhexstr(n):
    """Make a random password and return as string"""

    return hexlify(os.urandom(n))


def rand32():
    """Return a random 32-bit integer"""
    s = os.urandom(4)
    return ord(s[0]) | (ord(s[1]) << 8) | (ord(s[2]) << 16) | (ord(s[3]) << 24)


# Security identifiers for each part of the tunnel
remote_local_spi = "%#0#x" % rand32()
local_remote_spi = "%#08x" % rand32()

sel_template = """spdadd %(there)s  %(here)s any -P %(direction)s ipsec
    esp/tunnel/%(remote)s-%(local)s/require;
"""


prologue = """#! /usr/sbin/setkey -f

#
# IPSec static tunnel configuration
# Autogenerated by %(prog)s
# Date: %(date)s
#
# Local  = %(local)s
# Remote = %(remote)s

flush;
spdflush;

#
# For AES-CTR mode keyspec is 36 bytes long:
#  - first 256 bits (32 bytes) are used as the key
#  - last   32 bits ( 4 bytes) are used as nonce
#

add %(remotepub)s %(localpub)s esp %(remote_local_spi)s
    -m tunnel -r 32
    -E aes-ctr     0x%(RL_enc)s
    -A hmac-sha256 0x%(RL_mac)s;

add %(localpub)s %(remotepub)s esp %(local_remote_spi)s
    -m tunnel -r 32
    -E aes-ctr     0x%(LR_enc)s
    -A hmac-sha256 0x%(LR_mac)s;

"""



epilogue = """# End of rules


dump;
spddump;

# EOF
"""



def add_rule(local, remote, here_nets, there_nets, direction):
    d = {
        'local':    local,
        'remote':   remote,
        'direction':direction,
    }

    rules = "# Rules for packets %s\n\n" % direction
    for here in here_nets:
        for there in there_nets:
            d['here']  = here
            d['there'] = there
            rules += sel_template % d
            rules += "\n"

    return rules


def writefile(fn, s):
    tmp = "%s%u" % (fn, rand32())
    fd  = open(tmp, "w")
    fd.write(s)
    fd.close()
    os.chmod(tmp, 0600)
    os.rename(tmp, fn)


def a_to_b(d, b, outfile):

    in_rules  = add_rule(b.A, b.B, b.Anets, b.Bnets, 'in')
    out_rules = add_rule(b.B, b.A, b.Bnets, b.Anets, 'out')
    #in_rules  = add_rule(lpub, rpub, lnets, rnets, 'in')
    #out_rules = add_rule(rpub, lpub, rnets, lnets, 'out')

    #d['local_remote_spi'] = b.AB_spi
    #d['remote_local_spi'] = b.BA_spi
    #d['LR_enc'] = b.AB_ekey
    #d['RL_enc'] = b.BA_ekey

    #d['LR_mac'] = b.AB_mkey
    #d['RL_mac'] = b.BA_mkey

    d['local']  = b.A
    d['remote'] = b.B

    rules  = prologue % d
    rules += """

%s


%s

%s""" % (in_rules, out_rules, epilogue)

    writefile(outfile, rules)


class bundle:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

def grokspec(s, dn):
    """Grok a IP:nets,... specification"""

    i = s.find(':')
    if i < 0:
        die("%s specification '%s' doesn't look like IP:subnet", dn, s)


    ip = s[:i]
    s  = s[i+1:]
    return ip, s.split(',')


def main():
    global __doc__, Epilog

    usage = """%s [options] LOCAL-spec REMOTE-spec""" % Z

    parser = argparse.ArgumentParser(description=__doc__, usage=usage,
                            epilog=Epilog,
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", dest='verbose', action="store_true",
                      default=False,
                      help="Show verbose progress messages [False]")
    parser.add_argument("-l", "--local-file", dest='local', default="", metavar='F',
                        help="Write local config to file 'F' [$LOCAL_IP]")
    parser.add_argument("-r", "--remote-file", dest='remote', default="", metavar='F',
                        help="Write remote config to file 'F' [$REMOTE_IP]")

    parser.add_argument("localspec",  nargs=1, metavar="Local-Spec",
                        help="Local IP and subnet specification")
    parser.add_argument("remotespec", nargs=1, metavar="Remote-Spec",
                        help="Remote IP and subnet specification")

    a    = parser.parse_args()


    l_pub, l_nets = grokspec(a.localspec[0], "local")
    r_pub, r_nets = grokspec(a.remotespec[0], "remote")

    lr_e = randhexstr(36)
    rl_e = randhexstr(36)
    lr_m = randhexstr(32)
    rl_m = randhexstr(32)

    lr_spi = "0x%x" % rand32()
    rl_spi = "0x%x" % rand32()

    now  = datetime.datetime.now()
    d = { 'prog': sys.argv[0],
          'date': "%s" % now,
          'remotepub': r_pub,
          'localpub': l_pub,
          'local_remote_spi': lr_spi,
          'remote_local_spi': rl_spi,
          'LR_enc': lr_e,
          'RL_enc': rl_e,
          'LR_mac': lr_m,
          'RL_mac': rl_m,
        }


    lf = "%s-%s.conf" % (l_pub, r_pub)
    rf = "%s-%s.conf" % (r_pub, l_pub)

    if len(a.local) > 0:   lf = a.local
    if len(a.remote) > 0:  rf = a.remote


    if lf == rf:
        die("Local and Remote config filenames are identical: '%s'", lf)


    lr = bundle(A=l_pub, B=r_pub, Anets=l_nets, Bnets=r_nets,
                AB_spi=lr_spi,
                BA_spi=rl_spi,
                AB_ekey=lr_e,
                BA_ekey=rl_e,
                AB_mkey=lr_m,
                BA_mkey=rl_m)

    rl = bundle(A=r_pub, B=l_pub, Anets=r_nets, Bnets=l_nets,
                AB_spi=rl_spi,
                BA_spi=lr_spi,
                AB_ekey=rl_e,
                BA_ekey=lr_e,
                AB_mkey=rl_m,
                BA_mkey=lr_m)



    # Generate remote and local configs
    a_to_b(d, lr, lf)
    a_to_b(d, rl, rf)


main()

# EOF
