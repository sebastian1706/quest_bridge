import pathlib
s = pathlib.Path('/usr/local/lib/python3.10/site-packages/vuer/server.py')
s.write_text(s.read_text().replace(
    'from params_proto import Flag, PrefixProto, Proto',
    'from params_proto import PrefixProto, Proto\nFlag = bool'
))
