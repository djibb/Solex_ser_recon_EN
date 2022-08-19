# -*- coding: utf-8 -*-
"""
@author: Valerie Desnoux
with improvements by Andrew Smith
contributors: Jean-Francois Pittet, Jean-Baptiste Butet, Pascal Berteau, Matt Considine
Version 4 July 2022

--------------------------------------------------------------
Front end of spectroheliograph processing of SER and AVI files
- interface able to select one or more files
- call to the solex_recon module which processes the sequence and generates the PNG and FITS files
- offers with openCV a display of the resultant image
- wavelength selection with the pixel shift function, including multiple wavelengths and a range of wavelengths
- geometric correction with a fixed Y/X ratio
- if Y/X is blank, then this will be calculated automatically
--------------------------------------------------------------

"""
import math
import numpy as np

import os
import sys
import json
import Solex_recon as sol
from astropy.io import fits
import cProfile
import PySimpleGUI as sg
import traceback
import cv2


def usage():
    usage_ = "SHG_MAIN.py [-dcfpstwm] [file(s) to treat, * allowed]\n"
    usage_ += "'d' : 'flag_display', display all graphics (False by default)\n"
    usage_ += "'c' : 'clahe_only',  only final clahe image is saved (False by default)\n"
    usage_ += "'f' : 'save_fit', save all fits files (False by default)\n"
    usage_ += "'m' : 'mirror flip', mirror flip in x-direction (False by default)\n"
    usage_ += "'p' : 'disk_display' produce black disk with protuberance images (True by default)\n"
    usage_ += "'s' : 'crop_square_width', crop the width to equal the height (False by default)\n"
    usage_ += "'t' : 'disable transversalium', disable transversalium correction (False by default)\n"
    usage_ += "'v' : 'transversalium correction', add an int between 1 and 999 from strength of transversalium : -v45 \n"
    usage_ += "'w' : 'a,b,c'  produce images at a, b and c pixels. -w1,3,5\n"
    usage_ += "'w' : 'x:y:w'  produce images starting at x, finishing at y, every w pixels. -w1:30:5"
    return usage_


def treat_flag_at_cli(argument):
    """read cli arguments and produce options variable"""
    global options
    # reading arguments
    i = 0
    while i < len(argument[1:]):  # there's a '-' at first)
        character = argument[1:][i]
        if character == 'h':  # asking help menu
            print(usage())
            sys.exit()
        elif character == 'w':
            # find characters for shifting
            shift = ''
            stop = False
            try:
                while not stop:
                    if argument[1:][i+1].isdigit() or argument[1:][i+1] == ':' or argument[1:][i+1] == ',' or argument[1:][i+1] == '-':
                        shift += argument[1:][i+1]
                        i += 1
                    else:
                        i += 1
                        stop = True
            except IndexError:
                i += 1  # the reach the end of arguments.
            shift_choice = shift.split(':')
            if len(shift_choice) == 1:
                options['shift'] = list(
                    map(int, [x.strip() for x in shift.split(',')]))
            elif len(shift_choice) == 2:
                options['shift'] = list(
                    range(int(shift_choice[0].strip()), int(shift_choice[1].strip())+1))
            elif len(shift_choice) == 3:
                options['shift'] = list(range(int(shift_choice[0].strip()), int(
                    shift_choice[1].strip())+1, int(shift_choice[2].strip())))
            else:
                print('invalid shift input')
                sys.exit()

        elif character == 'v':
            try:
                stop = False
                value = ''
                while not stop:
                    if argument[1:][i+1].isdigit():
                        value += argument[1:][i+1]
                        i += 1
                    else:
                        stop = True
                        i += 1
            except:
                i += 1  # last caracter.
            value = int(value)
            if 1 < value < 999:
                options['trans_strength'] = value
            else:
                raise ValueError("bad transversalium value")

        elif character == 't':
            options['transversalium'] = False
            i += 1
        elif character == 'c':
            options['clahe_only'] = False
            i += 1
        elif character == 'p':
            options['disk_display'] = False
            i += 1
        else:
            try:  # all others
                options[flag_dictionnary[character]
                        ] = True if flag_dictionnary.get(character) else False
                i += 1
            except KeyError:
                print('ERROR !!! At least one argument is not accepted')
                print(usage())
                i += 1
    print('options %s' % (options))


def UI_SerBrowse(default_graphics, default_fits, default_clahe_only, default_crop_square, default_transversalium, default_transversalium_strength, default_rotation):
    global WorkDir, options
    sg.theme('Dark2')
    sg.theme_button_color(('white', '#500000'))

    layout = [
        [sg.Text('File(s)', size=(5, 1)), sg.InputText(default_text='', size=(75, 1), key='-FILE-', enable_events=True),
         sg.FilesBrowse('Open', file_types=(("SER Files", "*.ser"), ("AVI Files", "*.avi"),), initial_folder=WorkDir)],
        [sg.Checkbox('Show graphics', default=default_graphics, key='-DISP-')],
        [sg.Checkbox('Save fits files', default=default_fits, key='-FIT-')],
        [sg.Checkbox('Save clahe.png only',
                     default=default_clahe_only, key='-CLAHE_ONLY-')],
        [sg.Checkbox('Crop square', default=default_crop_square,
                     key='-crop_width_square-')],
        [sg.Checkbox('Mirror X', default=False, key='-flip_x-')],
        [sg.Text("Rotate png images:", key='img_rotate_slider')],
        [sg.Slider(range=(0, 270),
                   default_value=default_rotation,
                   resolution=90,
                   size=(25, 15),
                   orientation='horizontal',
                   font=('Helvetica', 12),
                   key='-img_rotate-')],
        [sg.Checkbox('Correct transversalium lines', default=default_transversalium,
                     key='-transversalium-', enable_events=True)],
        [sg.Text("Transversalium correction strength (pixels x 100) :",
                 key='text_trans', visible=default_transversalium)],
        [sg.Slider(range=(0.5, 7),
                   default_value=default_transversalium_strength,
                   resolution=0.5,
                   size=(25, 15),
                   orientation='horizontal',
                   font=('Helvetica', 12),
                   key='-trans_strength-',
                   visible=default_transversalium)],
        [sg.Text('Y/X ratio (blank for auto)', size=(25, 1)),
         sg.Input(default_text='', size=(8, 1), key='-RATIO-')],
        [sg.Text('Tilt angle (blank for auto)', size=(25, 1)), sg.Input(
            default_text='', size=(8, 1), key='-SLANT-', enable_events=True)],
        [sg.Text('Pixel offset', size=(25, 1)), sg.Input(default_text='0', size=(
            8, 1), tooltip="a,b,c will produce images at a, b and c\n x:y:w will produce images starting at x, finishing at y, every w pixels", key='-DX-', enable_events=True)],
        [sg.Text('Protus adjustment', size=(25, 1)), sg.Input(default_text='0', size=(
            8, 1), tooltip='make the black circle bigger or smaller by inputting an integer', key='-delta_radius-')],
        [sg.Button('OK'), sg.Cancel()]
    ]

    window = sg.Window('Processing', layout, finalize=True)
    window['-FILE-'].update(WorkDir)
    window.BringToFront()

    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED or event == 'Cancel':
            sys.exit()
        if event == '-FILE-':
            WorkDir = os.path.dirname(values['-FILE-'])+'/'
            os.chdir(WorkDir)
            read_ini()
            # TODO change GUI value from options{}
            window['-DISP-'].update(options['flag_display'])
            window['-FIT-'].update(options['save_fit'])
            window['-CLAHE_ONLY-'].update(options['clahe_only'])
            window['-crop_width_square-'].update(options['crop_width_square'])
            window['-flip_x-'].update(options['flip_x'])
            window['-img_rotate-'].update(int(options['img_rotate']))
            window['-transversalium-'].update(options['transversalium'])
            window['-trans_strength-'].update(
                int(options['trans_strength'])/100)
            window['-delta_radius-'].update(options['delta_radius'])
            window['-SLANT-'].update(options['slant_fix'])
            window['-RATIO-'].update(options['ratio_fixe'])

        if event == 'OK':
            if not values['-FILE-'] == WorkDir and not values['-FILE-'] == '':
                try:
                    serfiles, options = interpret_UI_values(values)
                    window.close()
                    return serfiles, options
                except Exception as inst:
                    sg.Popup('Error: ' + inst.args[0], keep_on_top=True)

            else:
                # display pop-up file not entered
                sg.Popup(
                    'Error: file not entered! Please enter file(s)', keep_on_top=True)
        window.Element(
            '-trans_strength-').Update(visible=values['-transversalium-'])
        window.Element('text_trans').Update(visible=values['-transversalium-'])


'''
open SHG.ini and read parameters
return parameters from file, or default if file not found or invalid
'''


def read_ini():
    # check for .ini file for working directory
    global options, WorkDir
    print('Check if .ini file is present')

    try:
        mydir_ini = os.path.join(os.path.dirname(sys.argv[0]), 'SHG_v2.ini')
        print('Attempting to read %s in %s directory' %
              (mydir_ini,  os.getcwd()))
        with open(mydir_ini, 'r') as fp:
            options_ = json.load(fp)
            options = options_.copy()
            WorkDir = options.pop('WorkDir')
        print('Reading OK')

    except FileNotFoundError:
        print('note: error reading .ini file - using default parameters')
        WorkDir = ''

    return WorkDir, options['flag_display'], options['save_fit'], options['clahe_only'], options['crop_width_square'], options['transversalium'], options['trans_strength']/100, options['img_rotate']


def save_ini_file():
    global options, WorkDir
    try:

        mydir_ini = os.path.join(os.path.dirname(sys.argv[0]), 'SHG_v2.ini')
        options_ = options.copy()
        options_['WorkDir'] = WorkDir
        print('Saving parameters in %s file in %s directory ' %
              (mydir_ini, os.getcwd()))
        with open(mydir_ini, 'w') as fp:
            json.dump(options_, fp, sort_keys=True, indent=4)

    except:
        traceback.print_exc()
        print('ERROR: couldnt write file ' + mydir_ini)


def interpret_UI_values(ui_values):
    try:
        shift = ui_values['-DX-']
        shift_choice = shift.split(':')
        if len(shift_choice) == 1:
            options['shift'] = list(map(int, [x.strip()
                                    for x in shift.split(',')]))
        elif len(shift_choice) == 2:
            options['shift'] = list(
                range(int(shift_choice[0].strip()), int(shift_choice[1].strip())+1))
        elif len(shift_choice) == 3:
            options['shift'] = list(range(int(shift_choice[0].strip()), int(
                shift_choice[1].strip())+1, int(shift_choice[2].strip())))
        else:
            raise Exception('invalid offset input!')
        if len(options['shift']) == 0:
            raise Exception(
                'Error: pixel offset input lower bound greater than upper bound!')
    except ValueError:
        raise Exception('invalid pixel offset value!')
    options['flag_display'] = ui_values['-DISP-']
    try:
        options['ratio_fixe'] = float(
            ui_values['-RATIO-']) if ui_values['-RATIO-'] else None
    except ValueError:
        raise Exception('invalid Y/X ratio value')
    try:
        options['slant_fix'] = float(
            ui_values['-SLANT-']) if ui_values['-SLANT-'] else None
    except ValueError:
        raise Exception('invalid tilt angle value!')
    try:
        options['delta_radius'] = int(ui_values['-delta_radius-'])
    except ValueError:
        raise Exception('invalid protus_radius_adjustment')
    options['save_fit'] = ui_values['-FIT-']
    options['clahe_only'] = ui_values['-CLAHE_ONLY-']
    options['crop_width_square'] = ui_values['-crop_width_square-']
    options['transversalium'] = ui_values['-transversalium-']
    options['trans_strength'] = int(ui_values['-trans_strength-']*100) + 1
    options['flip_x'] = ui_values['-flip_x-']
    options['img_rotate'] = int(ui_values['-img_rotate-'])
    serfiles = ui_values['-FILE-'].split(';')
    try:
        for serfile in serfiles:
            f = open(serfile, "rb")
            f.close()
    except:
        raise Exception('ERROR opening file :'+serfile+'!')
    return serfiles, options


def read_value_from_cli(arguments):
    global serfiles, WorkDir
    if len(arguments) > 1:
        for argument in arguments[1:]:
            if '-' == argument[0]:  # it's flag options
                treat_flag_at_cli(argument)
            else:  # it's a file or some files
                if serfiles == []:  # first pass
                    if argument.split('.')[-1].upper() == 'SER' or argument.split('.')[-1].upper() == 'AVI':
                        serfiles.append(argument)
        WorkDir = os.path.dirname(argument)+"/"
        os.chdir(WorkDir)
        print('theses files are going to be processed : ', serfiles)

# get and return options and serfiles from user using GUI


def inputUI():
    WorkDir, default_graphics, default_fits, default_clahe_only, default_crop_square, default_transversalium, default_transversalium_strength, default_rotation = read_ini()
    serfiles, options = UI_SerBrowse(default_graphics, default_fits, default_clahe_only, default_crop_square, default_transversalium,
                                     default_transversalium_strength, default_rotation)  # TODO as options is defined as global, only serfiles could be returned
    return options, serfiles, WorkDir


"""
-------------------------------------------------------------------------------------------
le programme commence ici !
--------------------------------------------------------------------------------------------
"""
serfiles = []
WorkDir = ''

options = {
    'shift': [0],
    'flag_display': False,
    'ratio_fixe': 0,
    'slant_fix': 0,
    'save_fit': False,
    'clahe_only': True,
    'disk_display': True,  # protus
    'delta_radius': 0,
    'crop_width_square': False,
    'transversalium': True,
    'trans_strength': 301,
    'img_rotate': 0,
    'flip_x': False,
}

flag_dictionnary = {
    'd': 'flag_display',  # True False display all pictures
    'c': 'clahe_only',  # True/False
    'f': 'save_fit',  # True/False
    'p': 'disk_display',  # True/False protuberances
    'w': 'shift',
    's': 'crop_width_square',  # True / False
    't': 'transversalium',  # True / False
    'm': 'flip_x',  # True / False
    'v': 'trans_strength'  # a 000 to 999 value
}

# list of files to process
# add a command line argument.
read_value_from_cli(sys.argv)  # need once to know if it's a cli launch.


def do_work(cli=False):
    global options, WorkDir
    if len(serfiles) == 1:
        # 4000 #pour gerer la tempo des affichages des images resultats dans cv2.waitKey
        options['tempo'] = 60000
    else:
        options['tempo'] = 5000

    # boucle sur la liste des fichers
    for serfile in serfiles:
        if serfile == '':
            sys.exit()
        print('file %s is processing' % serfile)
        WorkDir = os.path.dirname(serfile)+"/"
        os.chdir(WorkDir)

        base = os.path.basename(serfile)
        if base == '':
            print('filename ERROR : ', serfile)
            sys.exit()

        # ouverture du fichier ser
        try:
            f = open(serfile, "rb")
            f.close()
        except:
            print('ERROR opening file : ', serfile)
            sys.exit()

        # save parameters to .ini file
        save_ini_file()
        try:
            sol.solex_proc(serfile, options.copy())
        except:
            print('ERROR ENCOUNTERED')
            traceback.print_exc()
            cv2.destroyAllWindows()


if 0:
    options, serfiles = inputUI()
    cProfile.run('do_work()', sort='cumtime')
else:
    # if no command line arguments, open GUI interface
    if len(serfiles) == 0:
        while True:
            options, serfiles, WorkDir = inputUI()
            do_work()
    else:
        ####SPECIAL NEED FOR INI FILES FROM CLI###
        read_ini()
        # need a second time to change values in options from cli.
        read_value_from_cli(sys.argv)
        do_work()
