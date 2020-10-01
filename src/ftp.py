import ftplib
import os

import settings


def upload_file(gateway_ip, path, file_name):
    try:
        with ftplib.FTP(host=gateway_ip, user=settings.FTP_USERNAME, passwd=settings.FTP_PASSWORD) as _ftp:
            with open(path + file_name, 'rb') as f:
                res = _ftp.storbinary('STOR %s' % file_name, f)
                res_format = res.split('\n')[0].split('-')
                res_code = res_format[0]
                '''
                if res_code == '226':
                    print(res_format[1] + ' [%s]' % filename)
                else:
                    print(res)
                '''
    except ftplib.error_perm as e:  # Error codes 500-599
        if e.args[0][0:3] == '530':
            print('[Upload_file] Login authentication failed')
        elif e.args[0][0:3] == '550':
            print('[Upload_file] Bad filename:', e)
        else:
            print(e.args[0])


def upload_image(gateway_ip, image_name, user_id, nodetype):
    binary_file = os.path.dirname(os.path.abspath(__file__)) + '/images/' + user_id + '/' + nodetype + '/' + image_name
    try:
        with ftplib.FTP(host=gateway_ip, user=settings.FTP_USERNAME, passwd=settings.FTP_PASSWORD) as _ftp:
            with open(binary_file, 'rb') as f:
                if not directory_exists(_ftp, 'images'):
                    _ftp.mkd('images')
                _ftp.cwd('images')

                if nodetype == 'UNO':
                    _dir = image_name.split('.')[0]
                    if not directory_exists(_ftp, _dir):
                        _ftp.mkd(_dir)
                    _ftp.cwd(_dir)
                    res = _ftp.storbinary('STOR %s' % image_name, f)
                else:
                    res = _ftp.storbinary('STOR %s' % image_name, f)
                    res_format = res.split('\n')[0].split('-')
                    res_code = res_format[0]
    except ftplib.error_perm as e:  # Error codes 500-599
        if e.args[0][0:3] == '530':
            print('[Upload_image] Login authentication failed')
        elif e.args[0][0:3] == '550':
            print('[Upload_image] Bad filename:', e)
        else:
            print(e.args[0])


def upload_erase_image(gateway_ip, path, image_name):
    try:
        with ftplib.FTP(host=gateway_ip, user=settings.FTP_USERNAME, passwd=settings.FTP_PASSWORD) as _ftp:
            with open(path + image_name, 'rb') as f:
                if not directory_exists(_ftp, 'images'):
                    _ftp.mkd('images')
                _ftp.cwd('images')
                if not directory_exists(_ftp, 'erase'):
                    _ftp.mkd('erase')
                _ftp.cwd('erase')

                _dir, ext = image_name.split('.')
                if ext == 'ino':
                    if not directory_exists(_ftp, _dir):
                        _ftp.mkd(_dir)
                    _ftp.cwd(_dir)

                res = _ftp.storbinary('STOR %s' % image_name, f)
                res_format = res.split('\n')[0].split('-')
                res_code = res_format[0]
                '''
                if res_code == '226':
                    print(res_format[1] + ' [%s]' % filename)
                else:
                    print(res)
                '''
    except ftplib.error_perm as e:  # Error codes 500-599
        if e.args[0][0:3] == '530':
            print('[Upload_erase_image] Login authentication failed')
        elif e.args[0][0:3] == '550':
            print('[Upload_erase_image] Bad filename:', e)
        else:
            print(e.args[0])


def download_xml(gateway_ip, gateways_xml_dir, file_name):
    try:
        with ftplib.FTP(host=gateway_ip, user=settings.FTP_USERNAME, passwd=settings.FTP_PASSWORD) as _ftp:
            with open(gateways_xml_dir + file_name, 'wb') as f:
                res = _ftp.retrbinary('RETR %s' % file_name, f.write)
                res_format = res.split('\n')[0].split('-')
                res_code = res_format[0]

                if res_code == '226':
                    print(res_format[1] + ' [%s]' % file_name)
                else:
                    print(res)

    except ftplib.error_perm as e:      # Error codes 500-599
        if e.args[0][0:3] == '530':
            print('[Download_xml] Login authentication failed')
        elif e.args[0][0:3] == '550':
            print('[Download_xml] Bad filename:', e)
        else:
            print(e.args[0])


def directory_exists(_ftp, _dir):
    filelist = []
    _ftp.retrlines('LIST', filelist.append)
    for f in filelist:
        if f.split()[-1] == _dir and f.upper().startswith('D'):
            return True
    return False
