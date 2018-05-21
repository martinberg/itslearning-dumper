# -*- coding: utf-8 -*-

# A dirty script to pull files from it's learning
# - Bart van Blokland

# USAGE:
# 0. Install Python 3.x (including pip) if you haven't already
# 1. Install required packages (`pip install -r requirements.txt`)
# 2. Run the script (`python scrape.py`)

# WHAT IS DOWNLOADED BY THIS SCRIPT?
# 1. All messages, both through the new and old system, including attachments
# 2. Bulletin messages and text posts, including comments
# 3. Assignments. 
#	3.1: If you're a student, your submission
#	3.2: If you teach the course, all student submissions, grades, and feedback
# 4. Forum posts. Includes any attached images.
# 5. Notes and links (both old and new style)
# 6. Surveys and tests (if you have sufficient access, the It's Learning generated reports are also snagged along)
# 7. Files

# The same folder structure as the course is kept.
# There may still be things the script doesn't grab. But at least the most important parts are there.

# You may need to set It's Learning's language to English (might be an innsida setting, not sure).
# Some bits and pieces rely on the english language pack (sorry, there was no easy other way)



# --- IMPORTS ---

# Imports for fixing freezing issues
from multiprocessing import Queue


import requests
from requests.exceptions import InvalidURL
from lxml.html import fromstring, tostring
from lxml import etree

# Python std lib imports
import argparse
import os.path
import os
import re
import html
import sys
import platform
import json
import traceback
import base64
from shutil import rmtree
from time import sleep
import getpass
from urllib.parse import urlparse
# Requires Python 3.4
from pathlib import Path

# --- SETTINGS ---

parser = argparse.ArgumentParser(description='Download files from itslearning. Check the README for more information.')

parser.add_argument('--output-dir', '-O', dest='output_dir', default=None,
					help='Defines the directory to output files from. If left empty, the program will prompt.')
parser.add_argument('--rate-limit-delay', '-R', dest='rate_limit', type=float, default=1,
					help="Rate limits requests to It's Learning (seconds). Defaults to 1 second.")
parser.add_argument('--skip-to-course', '-S', dest='skip_to_course', type=int, default=0,
					help='Skip to a course with a specific index. Useful after a crash. Set to 1 to only skip downloading internal messages.')
parser.add_argument('--enable-checkpoints', '-C', dest='enable_checkpoints', type=bool, default=False, 
					help='Save the location of the last element encountered by the dumping process. Useful for quick recovery while debugging, or being able to continue the dumping process at a later date.')
parser.add_argument('--output-text-extension', '-E', dest='output_extension', default='.html',
					help='Specifies the extension given to produced plaintext files. Values ought to be either ".html" or ".txt".')
parser.add_argument('--list', '-L', dest='do_listing', action='store_true',
					help='Don\'t dump anything, just list all courses and projects for each institution, along with their IDs.')
parser.add_argument('--projects-only', '-P', dest='projects_only', action='store_true',
					help='Only dump projects. No internal messages or courses are saved.')
parser.add_argument('--courses-only', '-F', dest='courses_only', action='store_true',
					help='Only dump courses. No internal messages or projects are saved.')
parser.add_argument('--messages-only', '-M', dest='messaging_only', action='store_true',
					help='Only dump internal messages. No courses or projects are saved.')
parser.add_argument('--recreate-dump-dir', '-D', dest='recreate_out_dir', action='store_true',
					help='Delete the output directory and recreate it (useful for debugging)')
parser.add_argument('--username', '-U', dest='username', default=None,
					help='Specify a username to be dumped')
parser.add_argument('--password', '-Q', dest='password', default=None,
					help='Specify a password of the user to be dumped')

args = parser.parse_args()

# I've sprinkled delays around the code to ensure the script isn't spamming requests at maximum rate.
# Each time such a delay occurs, it waits for this many seconds.
# Feel free to increase this if you plan to run this script overnight.
rate_limiting_delay_seconds = args.rate_limit

# Some bits and pieces of text may contain special characters. Since a number of these are used
# in file paths and file names, they have to be filtered out. 
# Filename characters are deleted from file names
# File path characters are only deleted from entire/complete file paths
# I may have missed one of two. 
invalid_path_characters = [':', ',', '*', '?', '"', '<', '>', '\t', '`', '´', '|']
invalid_filename_characters = [':', '.', ',', '*', '/', '\\', '?', '"', '<', '>', '\t', '`', '´', '|']

# All output files will receive this extension. Since a lot of stuff contains raw HTML, I used HTML
# as the file type. You may want to change this to .txt though, since many files also contain plaintext bits.
output_text_extension = args.output_extension

# Use if the program crashed and stopped early. Skips to a course with a specific index
# If this value is non-zero, also downloading of the messaging inbox will be skipped.
# The index is 1-indexed, and corresponds to the course index listed on the print messages in the console
# when the dumping of a new course is started.
skip_to_course_with_index = max(args.skip_to_course, (1 if args.courses_only or args.projects_only else 0))

# --- INTRO ---

if not args.do_listing:
	print('----- It\'s Learning dump script -----')
	print('Created by: Bart van Blokland (bart.van.blokland@ntnu.no)')
	print('Modified by: Fredrik Erlandsson (fer@bth.se) with further modifications from Martin Bergström')
	print()
	print('Greetings! This script will help you download your content off of It\'s Learning.')
	print('We\'ll start by selecting a directory where all the files are going to be saved.')
	if os.name == 'nt':
		print()
		print('NOTE: Since you\'re a Windows user, please keep in mind that file paths can only be 255 characters long. This is a Windows limitation I can\'t do anything about.')
		print('This script has a fallback option for files which can not be created due to this limitation by saving them to a single directory.')
		print('For the best results, I recommend creating a folder in the root of your hard drive. For example; C:\\dump or D:\\dump.')
		print('You can do this by clicking on My Computer while selecting a directory, double clicking on a hard drive, creating a directory named \'dump\', and selecting it.')
		print('This will cause the least number of files to overflow.')
	print()

	# Determines where the program dumps its output. 
	# Note that the tailing slash is mandatory. 
	output_folder_name = args.output_dir
	is_directory_empty = False
	while not is_directory_empty:
		if output_folder_name is None:
			input('Press Enter to continue and select a directory.')
			# User interface goodies
			try:
				# A bit ugly, but libraries already imported won't be imported again, so actually, all is good.
				import tkinter
				from tkinter.filedialog import askdirectory
			except ImportError as ie:
				print('')
				print('!!! Could not import tkinter.')
				print("If you don't have tkinter installed, specify the output dir by using the output parameter '--output-dir'")
				print('')
				raise ie
			tkinter.Tk().withdraw()
			output_folder_name = askdirectory()
		if output_folder_name == '':
			print('Folder selection cancelled. Aborting.')
			sys.exit(0)
		output_folder_name = os.path.abspath(output_folder_name)
		is_directory_empty = not os.listdir(output_folder_name)
		if args.recreate_out_dir and os.path.exists(output_folder_name):
			print('Recreating output directory..')
			rmtree(output_folder_name)
			os.makedirs(output_folder_name)
			is_directory_empty = not os.listdir(output_folder_name)
		if not is_directory_empty:
			print()
			print('The selected directory is not empty, which the script needs to work properly.')
			print('Press enter to try again, and select a new one.')
			print('You can always create a new directory and select it; that one will always be empty.')
			print()
			input('Press Enter to continue and try selecting a directory again.')
	print('Selected output folder:', output_folder_name)
elif args.recreate_out_dir and os.path.exists(output_folder_name):
	print('Recreating output directory..')
	rmtree(output_folder_name)
	os.makedirs(output_folder_name)


# If a crash occurs, the script can skip all elements in folders up to the point where it left off. 
# The state is stored in a small text file created inside the working directory.
# Turn this setting on to allow the creation of these checkpoints. They are only really useful if you can fix the issue causing the crash in the first place.
enable_checkpoints = args.enable_checkpoints

# --- CONSTANTS ---

innsida = 'https://hkr.itslearning.com/'
platform_redirection = 'https://hkr.itslearning.com/DashboardMenu.aspx?LocationType=Hierarchy'

institutions = ['hkr', ]

itslearning_gateway_url = {
	'hkr': 'https://hkr.itslearning.com/Index.aspx'}


itsleaning_course_list = {
	'hkr': 'https://hkr.itslearning.com/Course/AllCourses.aspx'}
itslearning_course_base_url = {
	'hkr': 'https://hkr.itslearning.com/ContentArea/ContentArea.aspx?LocationID={}&LocationType={}'}
itslearning_login_landing_page = {
	'hkr': 'https://hkr.itslearning.com/DashboardMenu.aspx'}
itslearning_course_bulletin_base_url = {
	'hkr': 'https://hkr.itslearning.com/Course/course.aspx?CourseId='}
itslearning_project_bulletin_base_url = {
	'hkr': 'https://hkr.itslearning.com/Project/project.aspx?ProjectId={}&BulletinBoardAll=True'}
itslearning_bulletin_next_url = {
	'hkr': 'https://hkr.itslearning.com/Bulletins/Page?courseId={}&boundaryLightBulletinId={}&boundaryLightBulletinCreatedTicks={}'}
itslearning_folder_base_url = {
	'hkr': 'https://hkr.itslearning.com/Folder/processfolder.aspx?FolderElementID='}
itslearning_file_base_url = {
	'hkr': 'https://hkr.itslearning.com/File/fs_folderfile.aspx?FolderFileID='}
itslearning_assignment_base_url = {
	'hkr': 'https://hkr.itslearning.com/essay/read_essay.aspx?EssayID='}
itslearning_note_base_url = {
	'hkr': 'https://hkr.itslearning.com/Note/View_Note.aspx?NoteID='}
itslearning_discussion_base_url = {
	'hkr': 'https://hkr.itslearning.com/discussion/list_discussions.aspx?DiscussionID='}
itslearning_weblink_base_url = {
	'hkr': 'https://hkr.itslearning.com/weblink/weblink.aspx?WebLinkID='}
itslearning_weblink_header_base_url = {
	'hkr': 'https://hkr.itslearning.com/weblink/weblink_header.aspx?WebLinkID=' }
itslearning_learning_tool_base_url = {
	'hkr': 'https://hkr.itslearning.com/LearningToolElement/ViewLearningToolElement.aspx?LearningToolElementId='}
itslearning_comment_service = {
	'hkr': 'https://hkr.itslearning.com/Services/CommentService.asmx/GetOldComments?sourceId={}&sourceType={}&commentId={}&count={}&numberOfPreviouslyReadItemsToDisplay={}&usePersonNameFormatLastFirst={}'}
itslearning_root_url = {
	'hkr': 'https://hkr.itslearning.com'}
itslearning_not_found = {
	'hkr': 'https://hkr.itslearning.com/not_exist.aspx'}
itslearning_test_base_url = {
	'hkr': 'https://hkr.itslearning.com/test/view_survey_list.aspx?TestID='}
old_messaging_api_url = {
	'hkr': 'https://hkr.itslearning.com/Messages/InternalMessages.aspx?MessageFolderId={}'}
itslearning_picture_url = {
	'hkr': 'https://hkr.itslearning.com/picture/view_picture.aspx?PictureID={}&FolderID=-1&ChildID=-1&DashboardHierarchyID=-1&DashboardName=&ReturnUrl='}
itslearning_online_test_url = {
	'hkr': 'https://hkr.itslearning.com/Ntt/EditTool/ViewTest.aspx?TestID={}'}
itslearning_online_test_details_postback_url = {
	'hkr': 'https://hkr.itslearning.com/Ntt/EditTool/ViewTestResults.aspx?TestResultId={}'}
itslearning_new_messaging_api_url = {
	'hkr': 'https://hkr.itslearning.com/restapi/personal/instantmessages/messagethreads/v1?threadPage={}&maxThreadCount=15'}
itslearning_all_projects_url = {
	'hkr': 'https://hkr.itslearning.com/Project/AllProjects.aspx'}
base64_png_image_url = {
	'hkr': 'https://hkr.itslearning.comdata:image/png;base64,'}
base64_jpeg_image_url = {
	'hkr': 'https://hkr.itslearning.comdata:image/jpeg;base64,'}
itslearning_unauthorized_url = {
	'hkr': 'https://hkr.itslearning.com/not_authorized.aspx'}

innsida_login_parameters = {'SessionExpired': 0}
progress_file_location = os.path.join(os.getcwd(), 'saved_progress_state.txt')

overflow_count = 0

# --- HELPER FUNCTIONS ---

def delay():
	sleep(rate_limiting_delay_seconds)

def convert_html_content(html_string):
	unescaped = html.unescape(html_string).split('\n')
	return '\n'.join([string.strip() for string in unescaped])

def sanitisePath(filePath):
	# I don't care about efficiency.
	for character in invalid_path_characters:
		# Fix for absolute paths on windows
		if os.name == 'nt' and os.path.isabs(filePath) and character == ':':
			filePath = filePath[0:2] + filePath[2:].replace(character, '')
		else:
			filePath = filePath.replace(character, '')
	filePath = '/'.join([m.strip() for m in filePath.split('/')])
	return filePath

def createUniqueFilename(path):
	path_exported = Path(path)
	folder_parts = path_exported.parts[0:-1]
	file_name = '.'.join(path_exported.name.split('.')[0:-1])
	extension = path_exported.name.split('.')[-1]
	count = 1
	while os.path.exists(path):
		path = '/'.join(folder_parts) + '/' + file_name + ' (Duplicate ' + str(count) + ').' + extension
		count += 1
	return path

def sanitiseFilename(filename):
	for character in invalid_filename_characters:
		filename = filename.replace(character, '')
	return filename

def makeDirectories(path):
	cleaned_path = sanitisePath(path)
	abs_path = os.path.abspath(cleaned_path)
	if not os.path.exists(abs_path):
		try: 
			os.makedirs(abs_path)
		except FileNotFoundError:
			print('COULD NOT CREATE A FOLDER AT: ')
			print(abs_path.encode('ascii', 'ignore'))
			print('If you\'re on Windows this can happen due to Windows being unable to handle paths longer than 255 characters.')
			print('Any files dumped in these directories will be redirected to the overflow directory.')
	return abs_path

# Windows has this amazing feature called "255 character file path limit"
# Here's a function made specifically for countering this issue.
def dumpToOverflow(content, filename):
	global overflow_count
	overflow_count += 1
	filepath, basename = os.path.split(os.path.normpath(sanitisePath(filename)))
	dirtree = filepath.split(os.sep)
	overflowDirectory = output_folder_name + '/' + dirtree[2] + '/Overflowed Files'
	if not os.path.exists(overflowDirectory):
		overflowDirectory = makeDirectories(overflowDirectory)
	total_path = sanitisePath(overflowDirectory + '/' + str(overflow_count) + '_' + basename)
	with open(total_path, 'wb') as file:
		file.write(content)
	# Create a txt file with original file location
	overflow_info_txt_filename = os.path.splitext(os.path.normpath(total_path))[0] + '.txt'
	original_location = ('Original file path: ' + filename).encode('utf-8')
	bytesToTextFile(original_location, overflow_info_txt_filename)
	print('FILE WAS WRITTEN TO OVERFLOW DIRECTORY - path too long (Windows issue)')
	print('Original file path:', filename.encode('ascii', 'ignore'))
	print('New file path:', total_path.encode('ascii', 'ignore'))

def bytesToTextFile(content, filename):
	filename = sanitisePath(filename)
	filename = os.path.abspath(createUniqueFilename(filename))
	if len(filename) >= 254 and 'Windows' in platform.system():
		dumpToOverflow(content, filename)
	else:
		with open(filename, 'wb') as file:
			file.write(content)

# Conversion between formats of one library to another
def convert_lxml_form_to_requests(lxml_form_values):
	form_dict = {}
	for item in lxml_form_values.form_values():
		form_dict[item[0]] = item[1]
	return form_dict

def do_feide_relay(session, relay_response):
	relay_page = fromstring(relay_response.text)
	relay_form = relay_page.forms[0]

	relay_form_dict = convert_lxml_form_to_requests(relay_form)

	return session.post(relay_form.action, data = relay_form_dict)

def download_file(institution, url, destination_directory, session, index=None, filename=None, disableFilenameReencode=False):
	try:
		file_download_response = session.get(url, allow_redirects=True)
	except Exception:
		# Can occur in a case of an encoded image. If so, dump it.
		if base64_png_image_url[institution] in url or base64_jpeg_image_url[institution] in url:
			try:
				extension = url.split(':')[2].split(';')[0].split('/')[1]
				print('\tDownloaded Base64 encoded {} image'.format(extension).encode('ascii', 'ignore'))
				start_index = url.index(',') + 1
				base64_encoded_file_contents = url[start_index:]
				decoded_bytes = base64.b64decode(base64_encoded_file_contents)
				bytesToTextFile(decoded_bytes, destination_directory + '/' + base64_encoded_file_contents[0:10] + '.' + extension)
			except Exception:
				print('Base64 Image Download Failed: unknown umage formatting. Skipping.')
			return
		elif url.startswith('/'):
			try:
				file_download_response = session.get(itslearning_root_url[institution] + url, allow_redirects=True)
			except Exception:
				print('FAILED TO DOWNLOAD FILE (INVALID URL):', url.encode('ascii', 'ignore'))
				return
		else:
			print('FAILED TO DOWNLOAD FILE (INVALID URL):', url.encode('ascii', 'ignore'))
			return
	
	# If links are not directed to it's learning, the header format might be different
	if filename is None:
		try:
			filename_header = file_download_response.headers['Content-Disposition']
			filename_start = filename_header.split('filename="')[1]
			filename_end = filename_start.find('"')
			filename = filename_start[0:filename_end]
		except (KeyError, IndexError):
			# Hope that the filename was part of the URL
			filename = os.path.basename(urlparse(url).path)

	if index is not None:
		filename = str(index) + '_' + filename

	# Fix shitty decoding done by requests
	if not disableFilenameReencode:
		initial_filename = filename
		try:
			filename = filename.encode('latin1').decode('utf-8')
		except UnicodeDecodeError:
			filename = initial_filename
		except UnicodeEncodeError:
			filename = initial_filename

	# Special case where the server puts slashes in the file name
	# sanitiseFilename() cuts away too many characters here.
	filename = filename.replace('/', '')
	
	print('\tDownloaded', filename.encode('ascii', 'ignore'))
	if not os.path.exists(destination_directory):
		destination_directory = makeDirectories(destination_directory)


	filename = sanitisePath(filename)
	total_file_name = os.path.abspath(sanitisePath(destination_directory) + "/" + filename)
	total_file_name = createUniqueFilename(total_file_name)
	if len(total_file_name) >= 255 and 'Windows' in platform.system():
		dumpToOverflow(file_download_response.content, total_file_name)
	else:
		with open(total_file_name, 'wb') as outputFile:
			outputFile.write(bytearray(file_download_response.content))

	# Add sleep for rate limiting
	delay()

	return filename

def doPostBack(page_url, postback_action, page_document, postback_parameter=None):
	postback_form = None
	for form in page_document.forms:
		if '__EVENTTARGET' in form.fields:
			postback_form = form
			break

	if postback_form is None:
		raise Exception('No postback form found on page!\nURL: ' + page_url)

	postback_form = page_document.forms[0]
	postback_form.fields['__EVENTTARGET'] = postback_action

	if postback_parameter is not None:
		postback_form.fields['__EVENTARGUMENT'] = postback_parameter

	post_data = convert_lxml_form_to_requests(postback_form)

	# Submitting the form to obtain the next page
	headers = {}
	headers['Referer'] = page_url

	messaging_response = session.post(page_url, headers=headers, data=post_data, allow_redirects=True)

	return messaging_response

def loadPaginationPage(page_url, current_page_document, backpatch_character_index = 6):
	next_page_button = current_page_document.find_class('previous-next')
	found_next_button = False
	for element in next_page_button:
		if len(element) > 0 and (element[0].get('title') == 'Next' or element[0].get('title') == 'Neste'):
			next_page_button = element
			found_next_button = True
			break

	if not found_next_button:
		print('\tItem complete: this was the last page')
		return False, None

	print('\tLoading next page')
	# Locating the event name for obtaining the next page
	post_back_event = next_page_button[0].get('id')
	
	# Backpatching event title
	post_back_event = list(post_back_event)
	post_back_event[backpatch_character_index] = '$'
	post_back_event = ''.join(post_back_event)

	messaging_response = doPostBack(page_url, post_back_event, current_page_document)

	return True, messaging_response


# --- DUMPING OF VARIOUS BITS OF ITS LEARNING FUNCTIONALITY ---

def processTest(institution, pathThusFar, testURL, session):
	test_response = session.get(testURL, allow_redirects = True)
	test_document = fromstring(test_response.text)
	
	test_title = test_document.find_class('ccl-pageheader')[0][0].text_content()
	print('\tDownloading test/survey:', test_title.encode('ascii', 'ignore'))

	dumpDirectory = pathThusFar + '/Test - ' + test_title
	dumpDirectory = sanitisePath(dumpDirectory)
	dumpDirectory = makeDirectories(dumpDirectory)

	manualDumpDirectory = dumpDirectory + '/Explicit dump'
	manualDumpDirectory = makeDirectories(manualDumpDirectory)

	try:
		# If we have access to downloading all results, we do so here.
		# Since 'we can, grabbing both XLS and HTML reports.'
		show_result_url = itslearning_root_url[institution] + test_document.get_element_by_id('result')[0].get('href')[2:]
		download_file(institution, show_result_url + '&Type=2', dumpDirectory, session, disableFilenameReencode=False)
		download_file(institution, show_result_url + '&Type=2&HtmlType=true', dumpDirectory, session, disableFilenameReencode=False)
		print('\tIt\'s Learning generated report downloaded.')
	except KeyError:
		# No problem that we can't see the 'show result button, the manual dump will catch whatever is visible to us'
		pass

	pages_remaining = True
	while pages_remaining:
		row_index = 0
		entries_remaining = True
		while entries_remaining:
			try:
				table_entry_element = test_document.get_element_by_id('row_{}'.format(row_index))
			except KeyError:
				# End the loop when there are no more submissions
				print('\tAll entries found on page.')
				entries_remaining = False
				continue

			index_offset = 0
			if len(table_entry_element[0]) > 0 and table_entry_element[0][0].get('id') is not None and 'check' in table_entry_element[0][0].get('id'):
				index_offset = 1

			entry_name = table_entry_element[0 + index_offset].text_content()
			entry_date = table_entry_element[1 + index_offset].text_content()
			try:
				entry_url = itslearning_root_url[institution] + table_entry_element[2 + index_offset][0].get('href')[2:]
			except IndexError:
				# Happens if you don't have access rights to view the responses.
				entry_url = None


			if entry_url is not None:
				print('\tDownloading response from', entry_name.encode('ascii', 'ignore'))
				entry_response = session.get(entry_url, allow_redirects=True)
				entry_document = fromstring(entry_response.text)

				file_content = convert_html_content(etree.tostring(entry_document.find_class('itsl-formbox')[0]).decode('utf-8')).encode('utf-8')

				file_name = manualDumpDirectory + '/' + sanitiseFilename(entry_name) + ' ' + sanitiseFilename(entry_date) + output_text_extension
				bytesToTextFile(file_content, file_name)
			else:
				print('\tSkipping response from', entry_name.encode('ascii', 'ignore'), ': No response present or insufficient privileges.')


			row_index += 1

			delay()

		# Searching for the next pagination button
		# Of course this page has its own mechanism for this
		next_page_button = test_document.find_class('previous-next')
		found_next_button = False
		for element in next_page_button:
			if len(element) > 0 and (element[0].get('title') == 'Next' or element[0].get('title') == 'Neste'):
				next_page_button = element
				found_next_button = True
				break

		if not found_next_button:
			print('\tNo more pages found. All items have been downloaded.')
			break

		next_page_url = html.unescape(next_page_button[0].get('href'))[2:]

		print('\tPage finished, moving on to next page.')
		test_response = session.get(itslearning_root_url[institution] + next_page_url, allow_redirects = True)
		test_document = fromstring(test_response.text)

def processNote(institution, pathThusFar, noteURL, session):
	note_response = session.get(noteURL, allow_redirects=True)
	note_document = fromstring(note_response.text)

	note_title_node = note_document.find_class('ccl-pageheader')[0]
	note_title = sanitiseFilename(note_title_node[0].text_content())
	
	print("\tDownloaded note:", note_title.encode('ascii', 'ignore'))

	dumpDirectory = pathThusFar + '/Note - ' + note_title
	dumpDirectory = sanitisePath(dumpDirectory)
	dumpDirectory = makeDirectories(dumpDirectory)

	note_content_div = note_document.find_class('h-userinput')[0]

	for image_tag in note_content_div.iterfind(".//img"):
		image_URL = image_tag.get('src')
		download_file(institution, image_URL, dumpDirectory, session)

	bytesToTextFile(etree.tostring(note_content_div), dumpDirectory + '/' + note_title + output_text_extension)

def processWeblink(institution, pathThusFar, weblinkPageURL, link_title, session):
	print('\tDownloading weblink: ', link_title.encode('ascii', 'ignore'))

	weblink_response = session.get(weblinkPageURL, allow_redirects=True)
	weblink_document = fromstring(weblink_response.text)

	header_frame = weblink_document.find(".//frame")
	header_src = header_frame.get('src')

	weblink_header_response = session.get(itslearning_weblink_header_base_url[institution] + header_src.split('=')[1], allow_redirects=True)
	weblink_header_document = fromstring(weblink_header_response.text)

	link_info_node = weblink_header_document.find_class('frameheaderinfo')[0]
	try:
		weblink_url = etree.tostring(link_info_node[0][1], encoding='utf-8')
	except IndexError:
		# Some older versions have some comment/section/other cruft. It's hard to tell how to get the info out consistently, so let's try one way and hope for the best.
		weblink_url = etree.tostring(link_info_node.find_class('standardfontsize')[0][1], encoding='utf-8')

	link_title = sanitiseFilename(link_title)

	link_file_content = (link_title + '\n\n').encode('utf-8') + weblink_url

	bytesToTextFile(link_file_content, pathThusFar + '/Link - ' + link_title + output_text_extension)

def processLearningToolElement(institution, pathThusFar, elementURL, session):
	element_response = session.get(elementURL, allow_redirects=True)
	element_document = fromstring(element_response.text)

	element_title = element_document.get_element_by_id('ctl00_PageHeader_TT').text
	element_title = sanitiseFilename(element_title)
	print('\tDownloaded Learning Tool Element: ', element_title.encode('ascii', 'ignore'))

	dumpDirectory = pathThusFar + '/Learning Tool Element - ' + element_title
	dumpDirectory = sanitisePath(dumpDirectory)
	dumpDirectory = makeDirectories(dumpDirectory)

	try:
		frameSrc = element_document.get_element_by_id('ctl00_ContentPlaceHolder_ExtensionIframe').get('src')

		frame_content_response = session.get(frameSrc, allow_redirects=True)
		bytesToTextFile(frame_content_response.content, dumpDirectory + '/page_contents' + output_text_extension)

		frame_content_document = fromstring(frame_content_response.text)
		for file_link in frame_content_document.find_class('file-link-link'):
			link_href = file_link[0].get('href')
			link_filename = file_link[0].get('download')
			download_file(institution, link_href, dumpDirectory, session, filename=link_filename)
	except KeyError:
		print('\tPage appears to have abnormal page structure. Falling back on dumping entire page as-is.')
		bytesToTextFile(etree.tostring(element_document, pretty_print=True, encoding='utf-8'), dumpDirectory + '/page_contents' + output_text_extension)
		
def processCustomActivity(institution, pathThusFar, custom_activityURL, session):
	custom_activity_response = session.get(custom_activityURL, allow_redirects=True)
	custom_activity_document = fromstring(custom_activity_response.text)

	custom_activity_title = custom_activity_document.get_element_by_id('ctl00_PageHeader_TT').text
	custom_activity_title = sanitiseFilename(custom_activity_title)
	print('\tDownloaded Custom Activity: ', custom_activity_title.encode('ascii', 'ignore'))

	dumpDirectory = pathThusFar + '/Result - ' + custom_activity_title
	dumpDirectory = sanitisePath(dumpDirectory)
	dumpDirectory = makeDirectories(dumpDirectory)

	custom_activity_ass = custom_activity_document.get_element_by_id('ctl00_ContentPlaceHolder_ContentContainer')

	bytesToTextFile(etree.tostring(custom_activity_ass, pretty_print=True, encoding='utf-8'), dumpDirectory + '/page_contents' + output_text_extension)

def processPicture(institution, pathThusFar, pictureURL, session):
	picture_response = session.get(pictureURL, allow_redirects=True)
	picture_document = fromstring(picture_response.text)

	element_title = picture_document.find_class('ccl-pageheader')[0].text_content()
	element_title = sanitiseFilename(element_title)
	print('\tDownloaded Picture:', element_title.encode('ascii', 'ignore'))

	dumpDirectoryPath = pathThusFar + '/Picture - ' + element_title
	dumpDirectoryPath = makeDirectories(dumpDirectoryPath)

	image_base_element = picture_document.find_class('itsl-formbox')[0]
	imageURL = itslearning_root_url[institution] + image_base_element[0][0].get('src')
	download_file(institution, imageURL, dumpDirectoryPath, session)

	description_text = etree.tostring(image_base_element[2], encoding='utf-8')
	bytesToTextFile(description_text, dumpDirectoryPath + "/caption" + output_text_extension)

def processDiscussionPost(institution, pathThusFar, postURL, postTitle, session):
	print("\tDownloading thread:", postTitle.encode('ascii', 'ignore'))
	post_response = session.get(postURL, allow_redirects=True)
	post_document = fromstring(post_response.text)

	post_table_tag = post_document.find_class('threadViewTable')[0]
	post_table_root = post_table_tag
	if post_table_root[0].tag == 'tbody':
			post_table_root = post_table_root[0]

	postDumpDirectory = pathThusFar + '/Thread - ' + sanitiseFilename(postTitle)
	completeDumpFile = postDumpDirectory
	duplicateCount = 1
	while os.path.exists(completeDumpFile):
		if duplicateCount > 1:
			completeDumpFile = postDumpDirectory + ' (Duplicate '+str(duplicateCount)+')'
		else:
			completeDumpFile = postDumpDirectory + ' (Duplicate)'
		duplicateCount += 1
	completeDumpFile = sanitisePath(completeDumpFile)

	fileContents = ''
	tags_to_next_entry = 0

	for index, post_tag in enumerate(post_table_root):
		if tags_to_next_entry != 0:
			# Each post is 3 tags
			tags_to_next_entry -= 1
			continue
		
		tags_to_next_entry = 2

		fileContents += '-------------------------------------------------------------------------\n'

		post_contents_tag = post_tag.getnext()

		is_post_deleted = 'deleted' in post_contents_tag[0][0].get('class')

		if is_post_deleted:
			# Deleted posts do not have a third footer entry like regular posts do, so we move on the the next page 1 tag earlier.
			tags_to_next_entry -= 1			

		if not is_post_deleted:
			footer_tag = post_contents_tag.getnext()

		try:
			author = 'Author: ' + post_tag[0][2][0].text
		except IndexError:
			# Fallback option, probably due to an anonymous post
			author = 'Author: ' + post_tag[0][0].get('alt')
		post_content = convert_html_content(etree.tostring(post_contents_tag[0][0]).decode('utf-8'))

		# Also download any images shown in the post
		for image_tag in post_contents_tag[0][0].iterfind(".//img"):
			imageDumpDirectory = pathThusFar + '/Attachments'
			if not os.path.exists(imageDumpDirectory):
				imageDumpDirectory = makeDirectories(imageDumpDirectory)

			image_URL = image_tag.get('src')

			# For some reason there can be images containing nothing on a page. No idea why.
			if image_URL is None: 
				continue

			# Special case for relative URL's: drop the It's Learning root URL in front of it
			if not image_URL.startswith('http'):
				image_URL = itslearning_root_url[institution] + image_URL

			download_file(institution, image_URL, imageDumpDirectory, session)

			delay()

		if not is_post_deleted:
			timestamp = footer_tag[0][0][0].text.strip()
		else:
			timestamp = ''

		fileContents += author + '\n' + timestamp + '\n\n' + post_content + '\n\n'

	bytesToTextFile(fileContents.encode('utf-8'), completeDumpFile + output_text_extension)

	# Add a time delay before moving on to the next post
	delay()

def processDiscussionForum(institution, pathThusFar, discussionURL, session):
	discussion_response = session.get(discussionURL, allow_redirects=True)
	discussion_document = fromstring(discussion_response.text)

	# They are sooo inconsistent with these conventions.
	discussion_title = sanitiseFilename(discussion_document.get_element_by_id('ctl05_TT').text)

	print("\tDownloaded discussion:", discussion_title.encode('ascii', 'ignore'))

	discussionDumpDirectory = pathThusFar + '/Discussion - ' + discussion_title
	discussionDumpDirectory = sanitisePath(discussionDumpDirectory)
	discussionDumpDirectory = makeDirectories(discussionDumpDirectory)


	# hacky way of retrieving the discussion ID, which we need for fetching the threads.
	discussionID = discussionURL.split('=')[1]

	# ThreadID starts counting at 1 because ID 0 is the table header.
	threadID = 1
	pages_remaining = True

	# Pagination
	while pages_remaining:

		nextThreadElement = discussion_document.get_element_by_id('Threads_' + str(threadID))
		if nextThreadElement[0].text is None or (not nextThreadElement[0].text.startswith('No threads') and not nextThreadElement[0].text.startswith('Inga trådar')):
			while nextThreadElement is not None and nextThreadElement != False:
				postURL = nextThreadElement[1][0].get('href')
				postTitle = nextThreadElement[1][0].text
				try:
					processDiscussionPost(institution, discussionDumpDirectory, itslearning_root_url[institution] + postURL, postTitle, session)
				except Exception:
					print('\n\nSTART OF ERROR INFORMATION\n\n\n\n')
					traceback.print_exc()
					print('\n\n\n\nEND OF ERROR INFORMATION')
					print()
					print('Oh no! The script crashed while trying to download the following discussion post:')
					print((itslearning_root_url[institution] + postURL).encode('ascii', 'ignore'))
					print('Some information regarding the error is shown above.')
					print('Please mail a screenshot of this information to bart.van.blokland@ntnu.no, and I can see if I can help you fix it.')
					print('Would you like to skip this item and move on?')
					print('Type \'skip\' if you\'d like to skip this element and continue downloading any remaining elements, or anything else if you\'d like to abort the download.')
					decision = input('Skip this element? ')
					if decision != 'skip':
						print('Download has been aborted.')
						sys.exit(0)
				threadID += 1
				try:
					nextThreadElement = discussion_document.get_element_by_id('Threads_' + str(threadID))
				except KeyError:
					nextThreadElement = False
		else:
			bytesToTextFile('No threads were created in this forum.'.encode('utf-8'), discussionDumpDirectory + '/No threads.txt')

		# Move on to next page
		found_next_page, discussion_response = loadPaginationPage(discussionURL, discussion_document, backpatch_character_index=7)

		if found_next_page:
			discussion_document = fromstring(discussion_response.text)
			# Start at the first thread on the next page
			threadID = 1
		else:
			pages_remaining = False



def processAssignment(institution, pathThusFar, assignmentURL, session):
	print("\tDownloading assignment:", assignmentURL.encode('ascii', 'ignore'))
	assignment_response = session.get(assignmentURL, allow_redirects=True)

	if itslearning_unauthorized_url[institution] in assignment_response.url:
		print('\t Access denied. Skipping.')
		return

	assignment_document = fromstring(assignment_response.text)
	#writeHTML(assignment_document, 'output.html')

	assignment_title = assignment_document.get_element_by_id('ctl05_TT').text

	dumpDirectory = pathThusFar + '/Assignment - ' + assignment_title
	dumpDirectory = sanitisePath(dumpDirectory)
	dumpDirectory = makeDirectories(dumpDirectory)

	assignment_answer_table = assignment_document.find_class('itsl-assignment-answer')
	
	# Download the assignment description
	details_sidebar_element = assignment_document.find_class('ccl-rwgm-column-1-3')[0]
	description_element = assignment_document.find_class('ccl-rwgm-column-2-3')[0]

	assignment_description = convert_html_content(etree.tostring(description_element[1], encoding='utf-8').decode('utf-8'))
	
	details_element = details_sidebar_element[1]
	assignment_details = ''

	for element in details_element:
		# Just dump the table on the right sidebar as-is
		assignment_details += ' '.join(convert_html_content(element.text_content()).split('\n')).strip() + '\n'

	assignment_details += '\nTask description:\n\n' + assignment_description

	bytesToTextFile(assignment_details.encode('utf-8'), dumpDirectory + '/Assignment description' + output_text_extension)

	# Download assignment description files
	file_listing_element = description_element[2][1]
	for file_element in file_listing_element:
		file_url = file_element[0].get('href')
		download_file(institution, file_url, dumpDirectory, session)


	# Download own submission, but only if assignment was answered
	if assignment_answer_table:
		answerDumpDirectory = dumpDirectory + '/Own answer'
		answerDumpDirectory = makeDirectories(answerDumpDirectory)

		# For some reason not all answers have a tbody tag.
		assignment_answer_root = assignment_answer_table[0]
		if assignment_answer_root[0].tag == 'tbody':
			assignment_answer_root = assignment_answer_root[0]

		assessment_file_contents = ''.encode('utf-8')


		# Part 1: The table describing when you submitted, who evaluated you, etc
		baseInformationTable = assignment_answer_table[0].getprevious()
		while not baseInformationTable.tag == 'table':
			baseInformationTable = baseInformationTable.getprevious()
		if baseInformationTable[0].tag == 'tbody':
			baseInformationTable = baseInformationTable[0]
		for entry in baseInformationTable:
			if entry is None or entry[0] is None or entry[0].text is None:
				continue
			assessment_file_contents += (entry[0].text + ': ').encode('utf-8') + etree.tostring(entry[1], encoding='utf-8') + '\n'.encode('utf-8')


		# Part 2: The table containing your submitted files and feedback
		for entry in assignment_answer_root:

			if entry is None or entry[0] is None or entry[0].text is None:
				continue		

			if entry[0].text.startswith('Files') or entry[0].text.startswith('Filer'):
				file_list_div = entry[1][0]
				for index, file_entry in enumerate(file_list_div):
					if file_entry.tag == 'section':
						continue
					if len(file_entry) == 0:
						continue

					file_index = None
					if len(file_list_div) > 2:
						file_index = index

					file_location = file_entry[0][0].get('href')
					download_file(institution, file_location, answerDumpDirectory, session, file_index)
			else:
				for attached_file in entry.find_class('ccl-iconlink'):
					file_location = attached_file.get('href')
					download_file(institution, file_location, answerDumpDirectory, session)
				assessment_file_contents += (entry[0].text + ': ').encode('utf-8') + etree.tostring(entry[1], encoding='utf-8') + '\n'.encode('utf-8')


		bytesToTextFile(assessment_file_contents, answerDumpDirectory + '/assessment.html')

	filter_box_present = True
	try:
		assignment_document.get_element_by_id('EssayAnswers_ctl00_groupFilter_filter')
	except KeyError:
		filter_box_present = False

	# First, we'll try to disable all filters, to ensure everything is downloaded.
	if filter_box_present:
		filter_elements = assignment_document.get_element_by_id('EssayAnswers_ctl00_groupFilter_filter')
		# Check all filter checkboxes
		postback_form = None
		for form in assignment_document.forms:
			if '__EVENTTARGET' in form.fields:
				postback_form = form
				break

		# There should be a postback form on every page though
		if postback_form is not None:
			for form_input_name in postback_form.fields:
				if form_input_name.startswith('EssayAnswers$ctl00$groupFilter'):
					postback_form.inputs[form_input_name].checked = True
			# And do a postback to get a page with no filters applied
			postback_response = doPostBack(assignmentURL, 'EssayAnswers$ctl00$groupFilter', assignment_document, postback_parameter='filter')
			assignment_document = fromstring(postback_response.text)

	answers_submitted = True
	try:
		assignment_document.get_element_by_id('EssayAnswers_0')
		# Having 2 table entries is guaranteed if there are any answers present.
		# However, if any filters have been applied we need to ensure 
		if len(assignment_document.get_element_by_id('EssayAnswers_1')) <= 1:
			answers_submitted = False
	except Exception:
		answers_submitted = False
		print('\tNo answers detected.')

	if answers_submitted:
		

		student_submissions = dumpDirectory + '/Student answers'
		student_submissions = makeDirectories(student_submissions)

		# Index 0 is the table header, which we skip

		pages_remaining = True
		while pages_remaining:
			submission_index = 1
			answers_remaining = True
			while answers_remaining:
				try:
					submission_element = assignment_document.get_element_by_id('EssayAnswers_{}'.format(submission_index))
				except KeyError:
					# End the loop when there are no more submissions

					answers_remaining = False
					continue

				#for i in range(0, 10):
				#	try: 
				#		print(i, ':', etree.tostring(submission_element[i]))
				#	except IndexError:
				#		pass
						
				no_group_index_offset = 0
				if 'No group' in submission_element[2].text_content() or 'Ingen gruppe' in submission_element[2].text_content():
					no_group_index_offset = 1
				elif 'Manage' in submission_element[2].text_content() or 'Administrer' in submission_element[2].text_content():
					no_group_index_offset = 1
				elif 'New group' in submission_element[2].text_content() or 'Ny gruppe' in submission_element[2].text_content():
					no_group_index_offset = 1

				#print("Index offset:", no_group_index_offset)

				# Exploits that solution links have no text with coloured highlighting
				try:
					plagiarism_text_element = submission_element[6 + no_group_index_offset][0]
					has_plagiarism_report = plagiarism_text_element.get('class') is not None and ('colorbox' in plagiarism_text_element.get('class') or 'h-hidden' in plagiarism_text_element.get('class'))
				except IndexError:
					has_plagiarism_report = False

				plagiarism_index_offset = 0
				if has_plagiarism_report:
					plagiarism_index_offset = 1
				score_index_offset = 1

				#print('plagiarism offset:', plagiarism_index_offset)


				# Column 0: Checkbox
				# Column 1: Student names
				try:
					students = [link[0].text for link in submission_element[1].find_class('ccl-iconlink')]
				except Exception:
					students = [submission_element[1].text_content()]
				if not students:
					students = [submission_element[1].text_content()]
				# Column 2: Submission date/time
				submission_time = submission_element[2 + no_group_index_offset].text
				# Column 3: Review date
				review_date = submission_element[3 + no_group_index_offset].text
				# Column 4: Status
				status = submission_element[4 + no_group_index_offset].text_content()
				# Column 5: Score
				# If nobody answered the assignment, all of the next elements are not present and thus will fail
				try:
					if not ('Show' in submission_element[5 + no_group_index_offset].text_content() or 'Vis' in submission_element[5 + no_group_index_offset].text_content()):
						score = submission_element[5 + no_group_index_offset].text
					else:
						# We have hit the assignment details link. This requires adjusting the offset
						score_index_offset = 0
						score = None

				except IndexError:
					score = None
				# Column 6: Plagiarism status
				if has_plagiarism_report:
					try:
						plagiarism_status = submission_element[6 + no_group_index_offset].text_content()
					except IndexError:
						plagiarism_status = None
				else:
					plagiarism_status = None
				# Column 7: Show (link to details page)
				try:
					# Exploit that the last entry is always the details link
					details_page_url = itslearning_root_url[institution] + submission_element[len(submission_element) - 1][0].get('href')
				except IndexError:
					details_page_url = None

				has_submitted = submission_time is not None and not 'Not submitted' in submission_time and not 'Ikke levert' in submission_time
				if submission_time is None:
					submission_time = 'Not submitted.'
				if review_date is None:
					review_date = 'Not assessed.'
				if score is None:
					score = ''
				if plagiarism_status is None:
					plagiarism_status = 'No plagiarism check has been done.'


				print('\tDownloading assignment submission ', students[0].encode('ascii', 'ignore'))

				comment_field_contents = ''
				details_page_content = None

				# Only download solution if one was submitted
				if has_submitted:
					details_page_response = session.get(details_page_url, allow_redirects = True)
					details_page_content = fromstring(details_page_response.content)

					assessment_form_element = details_page_content.get_element_by_id('AssessForm')

					comment_field_element = assessment_form_element.get_element_by_id('AssessForm_comments_EditorCKEditor_ctl00')
					comment_field_contents = convert_html_content(etree.tostring(comment_field_element).decode('utf-8'))
				
				answer_directory = student_submissions + '/' + sanitiseFilename(students[0])
				answer_directory = makeDirectories(answer_directory)

				# Write out assessment details to a file
				answer_info = 'Students:\n'
				for student in students:
					answer_info += '\t- ' + student + '\n'
				answer_info += 'Submission Time: ' + submission_time + '\n'
				answer_info += 'Review Date: ' + review_date + '\n'
				answer_info += 'Status: ' + status + '\n'
				answer_info += 'Score: ' + score + '\n'
				answer_info += 'Plagiarism status: ' + plagiarism_status + '\n'
				answer_info += 'Comments on assessment: \n\n' + comment_field_contents + '\n'

				bytesToTextFile(answer_info.encode('utf-8'), answer_directory + '/Answer' + output_text_extension)

				# Again, only download files if there is a submission in the first place.
				if has_submitted:
					# Case 1: A plagiarism check was performed
					has_checked_files = True
					try:
						file_listing_element = assessment_form_element.find_class('tablelisting')[0][0]
					except IndexError:
						has_checked_files = False
					if has_checked_files:
						for link in file_listing_element.iterlinks():
							# We only want URLs for files.
							# Contrary to what it might seem iterlinks iterates over anything with an external URL in it.
							if not link[0].tag == 'a':
								continue
							# We also don't want plagiarism reports
							if '/essay/PlagiarismReport.aspx' in link[2]:
								continue
							download_file(institution, link[2], answer_directory, session, filename=html.unescape(link[0].text_content()), disableFilenameReencode=True)
					
					# Case 2: No plagiarism check was performed
					has_unchecked_files = True
					try:
						file_listing_element = assessment_form_element.get_element_by_id('AssessForm_ctl02_FileList')[1]
					except KeyError:
						has_unchecked_files = False
					if has_unchecked_files:
						for link_element in file_listing_element:
							download_file(institution, link_element[0].get('href'), answer_directory, session, filename=html.unescape(link_element[0].text_content()), disableFilenameReencode=True)


				
				submission_index += 1

			# Move on to the next page
			found_next_page, assignment_response = loadPaginationPage(assignmentURL, assignment_document, backpatch_character_index=12)

			if found_next_page:
				assignment_document = fromstring(assignment_response.text)
			else:
				pages_remaining = False

def processOnlineTestAttempt(institution, session, details_URL, dumpDirectory, attempt_index, student_name, attempt_file_contents):
	details_page_response = session.get(itslearning_root_url[institution] + details_URL, allow_redirects=True)
	details_page_document = fromstring(details_page_response.text)
	
	attempt_file_contents += '\n'

	# Dumping result data shown on page
	for result_details_element in details_page_document.find_class('ntt-test-result-status-label'):
		result_details_label = result_details_element.text_content().strip()
		result_details_value = result_details_element.getnext().text_content().strip().replace('  ', ' ').replace('\n', '')
		attempt_file_contents += result_details_label + ' ' + result_details_value + '\n'

	total_assessment_element = details_page_document.find_class('ccl-assess-badge')
	if len(total_assessment_element) > 0:
		attempt_file_contents += 'Assessment: ' + total_assessment_element[0].text_content().strip() + '\n'

	last_page_dumped = False

	attempt_file_contents += '\n-------------- Answers --------------\n\n'

	question_index = 1
	page_index = 1
	question_table_body = details_page_document.get_element_by_id('ctl00_ContentPlaceHolder_ResultsGrid_TB')

	attemptDirectory = dumpDirectory + '/' + sanitiseFilename(student_name) + '/Attempt ' + str(attempt_index)
	attemptDirectory = makeDirectories(attemptDirectory)

	while len(question_table_body) > 0:
		for question_element in question_table_body:
			print('\tSaving question', question_index)
			question_link = itslearning_root_url[institution] + question_element[0][1].get('href')
			
			question_title = question_element[1].text_content()
			attempt_file_contents += 'Question ' + str(question_index) + ': ' + question_title + '\n\n'
			
			question_response = session.get(question_link, allow_redirects=True)
			question_document = fromstring(question_response.text)

			try:
				question_result = question_document.find_class('question-result')[0].text_content()
				attempt_file_contents += question_result + '\n'
			except Exception:
				# Sometimes the score can be missing. This is a workaround so at least the script can continue.
				pass

			try:
				question_options_table = question_document.get_element_by_id('qti-choiceinteraction-container')

				for option_index, question_options_row in enumerate(question_options_table):
					if option_index == 0:
						attempt_file_contents += question_options_row.text_content() + '\n'
						continue
					if question_options_row.get('class') is not None and 'checkedrow' in question_options_row.get('class'):
						attempt_file_contents += 'Option (selected): ' + question_options_row.text_content() + '\n'
					else:
						attempt_file_contents += 'Option: ' + question_options_row.text_content() + '\n'
			except Exception:
				attempt_file_contents += 'Non Multiple Choice question. You can find the entire page in the folder titled "Attempt {}".\n'.format(question_index)

			# Need to download images from hotspot questions
			content_divs = question_document.find_class('content')
			for content_div in content_divs:
				for image_tag in content_div.iterfind(".//img"):

					image_URL = image_tag.get('src')

					# For some reason there can be images containing nothing on a page. No idea why.
					if image_URL is None: 
						continue

					# The image links produced by It's Learning for hotspot images have a bunch of spaces in front, plus a special character.
					# removing both of those here to obtain the relative link. Direct URL's are unaffected by this because they should not
					# contain spaces in the first place.
					image_URL = html.unescape(image_URL.split(' ')[-1])


					# Special case for relative URL's: drop the It's Learning root URL in front of it
					if not image_URL.startswith('http'):
						image_URL = itslearning_root_url[institution] + image_URL

					filename = download_file(institution, image_URL, attemptDirectory, session)
					if filename is None:
						filename = '(failed to download image)'
					attempt_file_contents += 'Attachment image: ' + filename + '\n'

					delay()
			
			bytesToTextFile(question_response.text.encode('utf-8'), attemptDirectory + '/Question ' + str(question_index) + '.html')

			attempt_file_contents += '\n'


			delay()
			question_index += 1

		print('\tPage finished, loading next one.')
		postback_form = None
		for form in details_page_document.forms:
			if '__EVENTTARGET' in form.fields:
				postback_form = form
				break

		if postback_form is None:
			raise Error('No postback form found on page!\nURL: ' + details_URL)

		# Extracting the destination URL from the form action field.
		# The URL starts with ./, so I'm removing the dot to obtain a complete URL
		form_action_url = itslearning_root_url[institution] + details_URL

		page_index += 1

		# This specific page requires these additional elements to do the postback
		postback_form = details_page_document.forms[0]
		postback_form.fields['__EVENTTARGET'] = 'ctl00$ContentPlaceHolder$ResultsGrid'
		postback_form.fields['ctl00$ContentPlaceHolder$ResultsGrid$HPN'] = str(page_index)
		postback_form.fields['ctl00$ContentPlaceHolder$ResultsGrid$HSE'] = ''
		postback_form.fields['ctl00$ContentPlaceHolder$ResultsGrid$HGC'] = ''
		postback_form.fields['ctl00$ContentPlaceHolder$ResultsGrid$HFI'] = ''

		post_data = convert_lxml_form_to_requests(postback_form)

		# Submitting the form to obtain the next page
		headers = {}
		headers['Referer'] = form_action_url

		details_page_response = session.post(form_action_url, headers=headers, data=post_data, allow_redirects=True)
		details_page_document = fromstring(details_page_response.text)
		question_table_body = details_page_document.get_element_by_id('ctl00_ContentPlaceHolder_ResultsGrid_TB')
		delay()
	print('\tAll pages have been loaded.')
	return attempt_file_contents

def dumpOnlineTestAnswerTable(institution, session, dumpDirectory, results_root_element, show_column_class, is_teacher):
	table_headers = []
	table_header_classes = []
	for index, table_row in enumerate(results_root_element):
		# results_root_element[0] is a <caption> element
		if index == 0:
			continue
		# results_root_element[1] contains table headers
		elif index == 1:
			for table_header in results_root_element[1]:
				table_headers.append(table_header.text_content())
				table_header_classes.append(table_header.get('class'))
			continue
		# If the table row lacks cells on the first data row, the table is empty.
		if index == 2 and len(table_row) == 1:
			break
		# The remainder of the table rows are attempts we want to save.
		attempt_file_contents = ''
		
		if not is_teacher:
			attempt_index = index - 1
			student_name = 'Own answer'
		details_URL = None

		for cell_index, table_cell in enumerate(table_row):
			table_cell_name = table_headers[cell_index]
			table_cell_class = table_header_classes[cell_index]
			table_cell_content = table_cell.text_content()
			if table_cell_class is not None and show_column_class in table_cell_class:
				details_URL = table_cell[0].get('href')
			else:
				attempt_file_contents += table_cell_name + ': ' + table_cell_content + '\n'
				if is_teacher and table_cell_class is not None and 'attempt' in table_cell_class:
					attempt_index = table_cell_content.strip()
				if is_teacher and table_cell_class is not None and ('name' in table_cell_class or 'nameH' in table_cell_class):
					student_name = table_cell_content.strip()
		
		# Only dumping the details afterwards so that we get a nice header in the output file containing the attempt details.
		if details_URL is not None:
			if not 'attempt_index' in locals():
				attempt_index = 1
			attempt_file_contents = processOnlineTestAttempt(institution, session, details_URL, dumpDirectory, attempt_index, student_name, attempt_file_contents)
		else:
			print('ERROR: COULD NOT FIND DETAILS PAGE OF ONLINE TEST.')
			print('NO DETAILS WILL BE SAVED OF THIS TEST.')


		try:
			bytesToTextFile(attempt_file_contents.encode('utf-8'), dumpDirectory + '/' + sanitiseFilename(student_name) + '/Attempt ' + str(attempt_index) + output_text_extension)
		except FileNotFoundError:
			print('\tFailed to save attempt. Usually occurs when an attempt could not be accessed, for instance when you or a student has aborted it prematurely.')

def processOnlineTest(institution, pathThusFar, nttUrl, nttID, session):
	online_test_response = session.get(nttUrl, allow_redirects=True)
	online_test_document = fromstring(online_test_response.text)

	# Special case for arbitrary It's Learning internal error
	if online_test_response.status_code // 100 == 5:
		print('It\'s Learning internal error occurred. Skipping.')
		return

	is_student = False
	is_teacher = False

	if 'ViewTestTeacher_Main.aspx' in online_test_response.url:
		is_teacher = True
	else:
		is_student = True

	redirected_page_URL = online_test_response.url

	
	test_title = online_test_document.get_element_by_id('ctl05_TT').text_content()
	print('\tDownloading Online Test:', test_title.encode('ascii', 'ignore'))

	dumpDirectory = pathThusFar + '/Online Test - ' + test_title
	dumpDirectory = sanitisePath(dumpDirectory)
	dumpDirectory = makeDirectories(dumpDirectory)

	has_submitted_answer = True
	try:
		results_root_element = online_test_document.get_element_by_id('ctl39_ResultsTable_table')
	except Exception:
		has_submitted_answer = False

	if has_submitted_answer and is_student:
			

		test_info_elements = online_test_document.find_class('itsl-detailed-info')
		
		# Extracting test information
		info_file_contents = ''

		for info_element in test_info_elements:
			for info_list_element in info_element:
				if len(info_list_element) >= 2:
					info_file_contents += info_list_element[0].text_content()
					info_file_contents += ' '
					info_file_contents += info_list_element[1].text_content()
					info_file_contents += '\n'
				else:
					# Dump whatever is inside the line if the indication was unclear.
					info_file_contents += info_list_element.text_content() + '\n'

		testIntro = online_test_document.find_class('NTT_TestDescriptionIntro')

		intro_text = ''.encode('utf-8')
		if len(testIntro) > 0:
			# Assuming there is only one of these
			testIntro = testIntro[0]
			intro_text += '\n\nTest Intro:\n\n'.encode('utf-8')
			intro_text += etree.tostring(testIntro, encoding='utf-8', pretty_print=True)


		bytesToTextFile(info_file_contents.encode('utf-8') + intro_text, dumpDirectory + '/Test Information' + output_text_extension)

		# Download test answers

		dumpOnlineTestAnswerTable(institution, session, dumpDirectory, results_root_element, 'showH', False)
	if is_teacher:
		# Read out test metadata
		test_information_element = online_test_document.find_class('ccl-rwgm-column-1-2')[0]
		test_description_element = online_test_document.find_class('ccl-rwgm-column-1-2')[1]

		test_information_table = test_information_element.find_class('description')[0]
		info_file_contents = ''

		for info_element in test_information_table:
			info_file_contents += info_element[0].text_content().strip() + ': ' + info_element[1].text_content().strip().replace('\n', '').replace('  ', ' ') + '\n'

		info_file_contents = (info_file_contents + '\n\nDescription:\n').encode('utf-8') + etree.tostring(test_description_element[1], encoding='utf-8')

		bytesToTextFile(info_file_contents, dumpDirectory + '/Test Information' + output_text_extension)

		pages_remaining = True
		page_id = 0
		while pages_remaining:

			# Read out entries from table
			results_table_element = online_test_document.get_element_by_id('resultsTable_table')
			dumpOnlineTestAnswerTable(institution, session, dumpDirectory, results_table_element, 'show', True)

			# Handle table pagination
			page_id += 1
			print('\tLoading next page')
			next_page_response = doPostBack(redirected_page_URL, 'resultsTable', online_test_document, postback_parameter='Paging:{}'.format(page_id))
			online_test_document = fromstring(next_page_response.text)
			results_table_element = online_test_document.get_element_by_id('resultsTable_table')

			if len(results_table_element) == 3 and len(results_table_element[2]) == 1:
				# Last page
				pages_remaining = False



def processFile(institution, pathThusFar, fileURL, session):
	file_response = session.get(fileURL, allow_redirects=True)

	#writeHTML(file_response, 'output.html')
	# Find all download links
	
	download_link_indices = [m.start() for m in re.finditer('/file/download\.aspx\?FileID=', file_response.text)]

	if len(download_link_indices) > 1:
		print('\tMultiple versions of file were found on page.')

	# Download each of them
	for index, link_start_index in enumerate(download_link_indices):
		link_end_index = file_response.text.find('"', link_start_index + 1)
		file_index = None
		if len(download_link_indices) > 1:
			file_index = index
			print('\tDownloading version {} of {}.'.format(index+1, len(download_link_indices)))
		
		download_file(institution, itslearning_root_url[institution] + file_response.text[link_start_index:link_end_index], pathThusFar, session, file_index)

def processFolder(institution, pathThusFar, folderURL, session, courseIndex, folder_state = [], level = 0, catch_up_state = None):
	print("\tDumping folder: ", pathThusFar.encode('ascii', 'ignore'))
	pathThusFar = sanitisePath(pathThusFar)
	if not os.path.exists(pathThusFar):
		pathThusFar = makeDirectories(pathThusFar)

	folder_response = session.get(folderURL, allow_redirects=True)
	#writeHTML(folder_response, 'output.html')
	folder_response_document = fromstring(folder_response.text)

	folder_contents_table = folder_response_document.get_element_by_id('ctl00_ContentPlaceHolder_ProcessFolderGrid_T')
	folder_contents_tbody = folder_contents_table[1]

	if folder_contents_tbody[0][0].get('class') == 'emptytablecell':
		print('\tFolder is empty.')
		return

	item_title_column = 1
	if folder_contents_table[0][0][0].get('class') == 'selectcolumn':
		item_title_column = 2

	for index, folder_contents_entry in enumerate(folder_contents_tbody):
		
		if catch_up_state is not None:
			target_course_id = catch_up_state[0]
			target_folder_state = catch_up_state[1]
			# We only want to fast-forward within the course we're catching up to
			if target_course_id == courseIndex and index < len(target_folder_state) and index < target_folder_state[level]:
				print('\tSkipping item to resume from saved state.')
				continue

		# Write the current status file (saves progress)
		if enable_checkpoints:
			if os.path.exists(progress_file_location):
				os.remove(progress_file_location)

			progress_file_contents = (str(courseIndex) + '\n' + ', '.join([str(i) for i in folder_state + [index]])).encode('utf-8')
			with open(progress_file_location, 'wb') as state_file:
				state_file.write(progress_file_contents)

		item_name = folder_contents_entry[item_title_column][0].text
		item_url = folder_contents_entry[item_title_column][0].get('href')

		try: 
			if item_url.startswith('/Folder'):
				folderURL = itslearning_folder_base_url[institution] + item_url.split('=')[1]
				processFolder(institution, pathThusFar + "/Folder - " + item_name, folderURL, session, courseIndex, folder_state + [index], level + 1)
			elif item_url.startswith('/File'):
				pass
				processFile(institution, pathThusFar, itslearning_file_base_url[institution] + item_url.split('=')[1], session)
			elif item_url.startswith('/essay'):
				pass
				processAssignment(institution, pathThusFar, itslearning_assignment_base_url[institution] + item_url.split('=')[1], session)
			elif item_url.startswith('/Note'):
				pass
				processNote(institution, pathThusFar, itslearning_note_base_url[institution] + item_url.split('=')[1], session)
			elif item_url.startswith('/discussion'):
				pass
				processDiscussionForum(institution, pathThusFar, itslearning_discussion_base_url[institution] + item_url.split('=')[1], session)
			elif item_url.startswith('/weblink'):
				pass
				processWeblink(institution, pathThusFar, itslearning_weblink_base_url[institution] + item_url.split('=')[1], item_name, session)
			elif item_url.startswith('/LearningToolElement'):
				pass
				processLearningToolElement(institution, pathThusFar, itslearning_learning_tool_base_url[institution] + item_url.split('=')[1], session)
			elif item_url.startswith('/test'):
				pass
				processTest(institution, pathThusFar, itslearning_test_base_url[institution] + item_url.split('=')[1], session)
			elif item_url.startswith('/picture'):
				pass
				processPicture(institution, pathThusFar, itslearning_picture_url[institution].format(item_url.split('=')[1]), session)
			elif item_url.startswith('/Ntt'):
				pass
				processOnlineTest(institution, pathThusFar, itslearning_online_test_url[institution].format(item_url.split('=')[1]), item_url.split('=')[1], session)
			elif item_url.startswith('/CustomActivity'):
				pass
				processCustomActivity(institution, pathThusFar, itslearning_learning_tool_custom_base_url[institution] + item_url.split('=')[1], session)
			else:
				print('Warning: Skipping unknown URL:', item_url.encode('ascii', 'ignore'))
		except Exception:
			print('\n\nSTART OF ERROR INFORMATION\n\n\n\n')
			traceback.print_exc()
			print('\n\n\n\nEND OF ERROR INFORMATION')
			print()
			print('Oh no! The script crashed while trying to download the following address:')
			print(item_url.encode('ascii', 'ignore'))
			print('Some information regarding the error is shown above.')
			print('Please mail a screenshot of this information to bart.van.blokland@ntnu.no, and I can see if I can help you fix it.')
			print('Would you like to skip this item and move on?')
			print('Type \'skip\' if you\'d like to skip this element and continue downloading any remaining elements, or anything else if you\'d like to abort the download.')
			decision = input('Skip this element? ')
			if decision != 'skip':
				print('Download has been aborted.')
				sys.exit(0)


		# Ensure some delay has occurred so that we are not spamming when querying lots of empty folders.
		delay()

def loadMessagingPage(institution, index, session):
	url = itslearning_new_messaging_api_url[institution].format(index)
	return json.loads(session.get(url, allow_redirects=True).text)

def processMessaging(institution, pathThusFar, session):
	batchIndex = 0
	threadIndex = 0
	messageBatch = loadMessagingPage(institution, batchIndex, session)

	dumpDirectory = os.path.join(os.path.join(pathThusFar, os.path.join('Messaging', institution.upper())), 'New API')
	dumpDirectory = makeDirectories(dumpDirectory)
	attachmentsDirectory = os.path.join(dumpDirectory, 'Attachments')
	attachmentsDirectory = makeDirectories(attachmentsDirectory)

	print('Downloading messages (sent through the new API)')

	while len(messageBatch['EntityArray']) > 0:
		print('\tDownloading message batch {}'.format(batchIndex))
		for messageThread in messageBatch['EntityArray']:
			threadFileContents = ''
			for message in messageThread['Messages']['EntityArray']:
				threadFileContents += 'From: ' + html.unescape(message['CreatedByName']) + '\n'
				threadFileContents += 'Sent on: ' + html.unescape(message['CreatedFormatted']) + '\n'
				if message['AttachmentName'] is not None:
					threadFileContents += 'Attachment: ' + html.unescape(message['AttachmentName']) + '\n'
				threadFileContents += '\n'
				threadFileContents += html.unescape(message['Text']) + '\n'
				threadFileContents += '\n'
				threadFileContents += '-------------------------------------------------------------------------\n'
				
				if message['AttachmentName'] is not None:
					download_file(institution, message['AttachmentUrl'], attachmentsDirectory, session, index=None, filename=None)#str(message['InstantMessageThreadId']) + '_' + message['AttachmentName'])
			thread_title = 'Message thread ' + str(threadIndex) + ' - ' + sanitiseFilename(messageThread['Created']) + '.txt'
			threadFileContents = threadFileContents.encode('utf-8')
			bytesToTextFile(threadFileContents, os.path.join(dumpDirectory, thread_title))
			threadIndex += 1

		delay()
		batchIndex += 1
		messageBatch = loadMessagingPage(institution, batchIndex, session)

	print('Downloading messages (send through the old API)')

	dumpDirectory = pathThusFar + '/Messaging/' + institution.upper() + '/Old API'
	dumpDirectory = makeDirectories(dumpDirectory)
	
	
	folderID = 1
	messaging_response = session.get(old_messaging_api_url[institution].format(folderID), allow_redirects=True)

	while messaging_response.url != itslearning_not_found[institution]:
		inbox_document = fromstring(messaging_response.text)
		inbox_title = inbox_document.get_element_by_id('ctl05_TT').text_content()
		print('\tAccessing folder {}'.format(inbox_title).encode('ascii', 'ignore'))
		
		boxDirectory = dumpDirectory + '/' + sanitiseFilename(inbox_title)
		boxDirectory = makeDirectories(boxDirectory)
		attachmentsDirectory = boxDirectory + '/Attachments'
		attachmentsDirectory = makeDirectories(attachmentsDirectory)

		first_message_entry_text = inbox_document.get_element_by_id('_table_1').text_content()
		no_messages_indication_present = 'No messages' in first_message_entry_text or 'Ingen meldinger' in first_message_entry_text

		if no_messages_indication_present:
			print('\tNo messages present in folder.')

		pagesRemain = not no_messages_indication_present
		message_index = 1
		message_index_on_page = 1
		while pagesRemain:

			# Needed to dig into a bunch of nested div's here.
			messages_remaining = True
			while messages_remaining:
				print('\tDownloading message {}'.format(message_index))
				try:
					message_element = inbox_document.get_element_by_id('_table_{}'.format(message_index_on_page))
					# Index 0: Checkbox
					# Index 1: Favourite star
					# index 2: Sender
					# Index 3: Title
					is_its_bug = False
					try:
						message_element[3][0].get('href')
					except IndexError:
						is_its_bug = True

					if not is_its_bug:
						message_url = itslearning_root_url[institution] + message_element[3][0].get('href')
					else:
						# Bug caused by having a < character in the recipients name
						message_url = itslearning_root_url[institution] + message_element[2][0][0][0].get('href')
					message_response = session.get(message_url, allow_redirects = True)
					message_document = fromstring(message_response.text)

					# In rare cases a message links to an unauthorized page. I have no idea why.
					if not message_response.url == itslearning_unauthorized_url[institution]:
						

						if not is_its_bug:
							has_attachment = len(message_element[4]) != 0
						else:
							print('WARNING: Its Learning has a bug in its old messaging system.')
							print('This bug appears to have occurred in this message.')
							print('Due to the unstable nature of this error, attachments can\'t be saved.')
							has_attachment = False

						
						# There's a distinction between sent/received and unsent ones. In the latter case we need to grab the message from the editor
						if 'sendmessage.aspx' in message_response.url:
							form_root = message_document.get_element_by_id('_inputForm')
							message_recipient = form_root[0][0][0][0][1].text_content()
							message_recipient += ' ' + form_root[0][0][1][0][1].text_content()
							message_sender = '[you]'
							message_title = convert_html_content(etree.tostring(form_root[0][0][2][0][1], encoding='utf8').decode('utf-8'))
							message_body = convert_html_content(etree.tostring(form_root.get_element_by_id('_inputForm_MessageText_MessageTextEditorCKEditor_ctl00'), encoding='utf8').decode('utf-8'))
							message_send_date = 'N/A'
							message_blind_recipient = None
							if has_attachment:
								print('ATTACHMENTS IN UNSENT MESSAGES ARE NOT SUPPORTED :(')
						else:
							message_title = message_document.get_element_by_id('ctl05_TT').text_content()
							# Eventually these indexing series will form a binarised version of the entire works of shakespeare
							message_header_element = message_document.find_class('readMessageHeader')[0][1]
							message_sender = convert_html_content(message_header_element[0][1].text_content())
							message_recipient = convert_html_content(message_header_element[1][1].text_content())
							message_body = convert_html_content(etree.tostring(message_document.find_class('readMessageBody')[0][1][0][0][0], encoding='utf8').decode('utf-8'))
							
							# Blind copy recipient handling
							message_blind_recipient = None
							blind_recipient_index = -1
							for entry_index, entry in enumerate(message_header_element):
								if len(entry) > 0 and ('Blind' in entry[0].text_content() or 'Blindkopi' in entry[0].text_content()):
									blind_recipient_index = entry_index
									break
							if blind_recipient_index != -1:
								message_blind_recipient = convert_html_content(message_header_element[blind_recipient_index][1].text_content())

							# It's Learning system messages have no link to the sender
							if len(message_header_element[0][1]) == 0:
								message_send_date = message_header_element[0][1].text_content()
							else:
								message_send_date = message_header_element[0][1][0].tail
							if has_attachment:
								attachment_index = -1
								for entry_index, entry in enumerate(message_header_element):
									if len(entry) > 0 and ('Attachments' in entry[0].text_content() or 'Vedlegg' in entry[0].text_content()):
										attachment_index = entry_index
										break
								if attachment_index != -1:
									attachment_filename = message_header_element[attachment_index][1][0].text_content()
									message_attachment_url = message_header_element[attachment_index][1][0].get('href')
									download_file(institution, itslearning_root_url[institution] + message_attachment_url, attachmentsDirectory, session, index=None, filename=attachment_filename, disableFilenameReencode=True)

						message_file_contents = 'From: ' + message_sender + '\n'
						message_file_contents = 'To: ' + message_recipient + '\n'
						message_file_contents += 'Subject: ' + message_title + '\n'
						message_file_contents += 'Sent on: ' + message_send_date + '\n'
						if message_blind_recipient is not None:
							message_file_contents += 'Blind copy: ' + message_blind_recipient + '\n'
						if has_attachment:
							message_file_contents += 'Attachment: ' + attachment_filename
						message_file_contents += 'Message contents: \n\n' + html.unescape(message_body)

						bytesToTextFile(message_file_contents.encode('utf-8'), boxDirectory + '/Message ' + str(message_index) + ' - ' + sanitiseFilename(message_send_date) + output_text_extension)

						delay()
						# Index 4: Has asttachments
						# Index 5: Received on
					else:
						print('WARNING: Message skipped because it linked to an unauthorized page. No idea why.')
				except KeyError:
					# End the loop when there are no more messages
					messages_remaining = False
					continue
				except Exception as e:
					print()
					print('---- START OF DEBUG INFORMATION ----')
					print()
					traceback.print_exc()
					print()
					print('Message info:')
					if 'message_element' in locals() and message_element is not None:
						print(etree.tostring(message_element))
					if 'message_header_element' in locals() and message_header_element is not None:
						print(etree.tostring(message_header_element))
					print()
					print('---- END OF DEBUG INFORMATION')
					print()
					print('Oh no! A crash occurred while trying to download the following message:')
					if 'message_url' in locals():
						print('URL:', message_url.encode('ascii', 'ignore'))
					if 'message_title' in locals():
						print('Subject:', message_title.encode('ascii', 'ignore'))
					print()
					print('This unfortunately means the contents of this message have probably not have been saved.')
					print('If you\'d like to help resolve this error, please send the marked debug information above to me.')
					print('You can reach me at bart.van.blokland@ntnu.no.')
					print('Press enter to skip this error, and continue to dump any remaining messages.')
					input()
				
				message_index_on_page += 1
				message_index += 1

			# Move on to the next page
			found_next_page, messaging_response = loadPaginationPage(old_messaging_api_url[institution].format(folderID), inbox_document)

			if found_next_page:
				inbox_document = fromstring(messaging_response.text)
				message_index_on_page = 1
			else:
				pagesRemain = False

		folderID += 1
		messaging_response = session.get(old_messaging_api_url[institution].format(folderID), allow_redirects=True)

def dumpSingleBulletin(institution, raw_page_text, bulletin_element, dumpDirectory, bulletin_index):
	# Post data
	author = bulletin_element.find_class('itsl-light-bulletins-person-name')[0][0][0].text_content()
	print('\tBulletin by', author.encode('ascii', 'ignore'))
	post_content = convert_html_content(bulletin_element.find_class('h-userinput itsl-light-bulletins-list-item-text')[0].get('data-text'))

	bulletin_file_content = 'Author: ' + author + '\n\n' + post_content

	# Comments
	# This is so hacky, you better not look for a moment
	# Here we get a specific line of javascript code containing a JSON object with all information we need
	bulletin_id = bulletin_element[0].get('data-bulletin-id')
	search_string = 'CCL.CommentModule[\'CommentModule_LightBulletin_' + str(bulletin_id) + '_CommentModule\'] = true;'

	code_start_index = raw_page_text.index(search_string)
	json_line_start_index = raw_page_text.index('\n', code_start_index)
	json_line_end_index = raw_page_text.index('\n', json_line_start_index + 1)
	json_line = raw_page_text[json_line_start_index:json_line_end_index].strip()
	
	# Cut the JSON object out of the line
	json_object_start_index = json_line.index('{')
	json_object_string = json_line[json_object_start_index:-2]
	
	# Parse the json object string
	comment_info = json.loads(json_object_string)

	# Only dump comments if there are any
	if comment_info['DataSource']['VirtualCount'] > 0:
		bulletin_file_content += '\n\n\n ---------- Comments ----------\n\n'
		for comment in comment_info['DataSource']['Items']:
			bulletin_file_content += 'Comment by: ' + comment['UserName'] + '\n'
			bulletin_file_content += 'Posted: ' + comment['DateTimeTooltip'] + '\n\n'
			bulletin_file_content += comment['CommentText'] + '\n\n'
			bulletin_file_content += ' -----\n\n'


		# If we didn't get all comments, load the rest
		if len(comment_info['DataSource']['Items']) < comment_info['DataSource']['VirtualCount']:
			sourceID = comment_info['UserData']['sourceId']
			sourceType = comment_info['UserData']['sourceType']
			# The comment ID seems to be the first in the list of comments
			commentId = comment_info['DataSource']['Items'][0]['Id']
			# Try to get all at once
			count = comment_info['DataSource']['VirtualCount']
			readItemsCount = comment_info['NumberOfPreviouslyReadItemsToDisplay']
			useLastName = comment_info['UsePersonNameFormatLastFirst']

			complete_comment_url = itslearning_comment_service[institution].format(sourceID, sourceType, commentId, count, readItemsCount, useLastName)
			additional_comments = json.loads(session.get(complete_comment_url, allow_redirects=True).text)

			delay()

			for additional_comment in additional_comments['Items']:
				bulletin_file_content += 'Comment by: ' + additional_comment['UserName'] + '\n'
				bulletin_file_content += 'Posted: ' + additional_comment['DateTimeTooltip'] + '\n\n'
				bulletin_file_content += additional_comment['CommentText'] + '\n\n'
				bulletin_file_content += ' -----\n\n'

	bytesToTextFile(bulletin_file_content.encode('utf-8'), dumpDirectory + '/Bulletin ' + str(bulletin_index) + output_text_extension)

def processBulletins(institution, pathThusFar, courseURL, session, courseID):
	bulletin_response = session.get(courseURL, allow_redirects=True)
	bulletin_document = fromstring(bulletin_response.text)

	is_new_style_bulletins = True

	# Test for what kinds of bulletins we're dealing with.
	# Basically just requesting lots of stuff that only exists in the new version and catching any errors produced
	try:
		attribute_value = bulletin_document.get_element_by_id('ctl00_ContentPlaceHolder_DashboardLayout_ctl04_ctl03_CT')[0][0].get('data-bulletin-item-editor-template')
		is_new_style_bulletins = attribute_value is not None
	except IndexError:
		is_new_style_bulletins = False

	if is_new_style_bulletins:
		bulletin_list_element = bulletin_document.get_element_by_id('ctl00_ContentPlaceHolder_DashboardLayout_ctl04_ctl03_CT')[0][0]

		# Don't dump bulletins if there aren't any
		if 'No bulletins' in bulletin_list_element[0].text_content() or 'Ingen oppslag' in bulletin_list_element[0].text_content():
			return

		dumpDirectory = pathThusFar + '/Bulletins'
		dumpDirectory = makeDirectories(dumpDirectory)

		bulletin_id = 0

		for index, bulletin_element in enumerate(bulletin_list_element):
			# Skip the box for writing a new bulletin
			if index == 0 and 'itsl-light-bulletins-new-item-listitem' in bulletin_element.get('class'):
				continue

			bulletin_id += 1

			dumpSingleBulletin(institution, bulletin_response.text, bulletin_element, dumpDirectory, bulletin_id)

		# Get initial next page settings
		field_name = '"InitialPageData"'
		json_field_start_index = bulletin_response.text.index(field_name)
		json_field_end_index = bulletin_response.text.index('}', json_field_start_index)
		next_bulletin_batch_string = '{' + bulletin_response.text[json_field_start_index:json_field_end_index] + '} }'
		next_bulletin_batch = json.loads(next_bulletin_batch_string)['InitialPageData']

		# Now we keep going until all bulletins have been downloaded
		while next_bulletin_batch['NeedToShowMore']:
			print('\tLoading more bulletins')
			additional_bulletins_response = session.get(itslearning_bulletin_next_url[institution].format(courseID, next_bulletin_batch['BoundaryLightBulletinId'], next_bulletin_batch['BoundaryLightBulletinCreatedTicks']))
			additional_bulletins_document = fromstring(additional_bulletins_response.text)

			for bulletin_element in additional_bulletins_document:
				# Final element means we need to extract the metadata to request the next page
				if bulletin_element.get('data-pagedata') is not None and 'NeedToShowMore' in bulletin_element.get('data-pagedata'):
					next_bulletin_batch = json.loads(html.unescape(bulletin_element.get('data-pagedata')))
					break

				bulletin_id += 1
				dumpSingleBulletin(institution, additional_bulletins_response.text, bulletin_element, dumpDirectory, bulletin_id)

			delay()
	bulletin_list_elements1 = bulletin_document.xpath('//div[@id = $elementid]', elementid = 'ctl00_ContentPlaceHolder_DashboardLayout_ctl04_ctl04_CT')
	bulletin_list_elements2 = bulletin_document.xpath('//div[@id = $elementid]', elementid = 'ctl00_ContentPlaceHolder_DashboardLayout_ctl04_ctl03_CT')
	bulletin_list_elements = [i.find_class('itsl-cb-news-old-bulletin-list') for i in (bulletin_list_elements1 + bulletin_list_elements2)]
	bulletin_list_elements = [item for sublist in bulletin_list_elements for item in sublist]

	text_elements = [i for i in (bulletin_list_elements1 + bulletin_list_elements2) if 'ilw-cb-text' in i.getparent().getparent().get('class')]

	is_old_style_bulletin = len(bulletin_list_elements) > 0 or len(text_elements) > 0

	if is_old_style_bulletin:
		# Some pages seem to be using one or the other, or both. A slow migration thing perhaps?
		
		message_count_thus_far = 0
		dumpDirectory = pathThusFar + '/Bulletins'

		for text_element in text_elements:
			# We found a text message
			print('\tFound text message')
			message_count_thus_far += 1

			try:
				message_title = text_element.getparent().getprevious()[0][0][0].text_content()
				message_content = convert_html_content(etree.tostring(text_element[0], encoding='utf-8').decode('utf-8')).strip()
				
				textDumpDirectory = dumpDirectory + '/Text messages'
				if not os.path.exists(textDumpDirectory):
					textDumpDirectory = makeDirectories(textDumpDirectory)

				message_file_contents = message_title + '\n\n' + message_content
			except IndexError:
				print('Failed to dump text message. This might be some other old-style course page element the script doesn\'t know about.')
				return

			bytesToTextFile(message_file_contents.encode('utf-8'), textDumpDirectory + '/Message ' + str(message_count_thus_far) + output_text_extension)

		for bulletin_list_element in bulletin_list_elements:

			# Special case for an occurrence of an empty element.
			if len(bulletin_list_element) == 0 or len(bulletin_list_element[0]) == 0:
				return
			elif bulletin_list_element.tag == 'ul':
				# We found a bulletin list

				if 'No bulletins' in bulletin_list_element[0].text_content() or 'Ingen oppslag' in bulletin_list_element[0].text_content():
					return

				if not os.path.exists(dumpDirectory):
					dumpDirectory = makeDirectories(dumpDirectory)

				bulletin_id = 0
				for list_element in bulletin_list_element:
					bulletin_id += 1

					bulletin_subject = convert_html_content(list_element[0].text_content()).strip()
					bulletin_message = convert_html_content(etree.tostring(list_element[1], encoding='utf-8').decode('utf-8')).strip()
					bulletin_author = convert_html_content(list_element[3][0].text_content()).strip()
					bulletin_post_date = convert_html_content(list_element[3][1].text_content()).strip()

					bulletin_file_content = 'Author: ' + bulletin_author + '\n'
					bulletin_file_content += 'Posted on: ' + bulletin_post_date + '\n'
					bulletin_file_content += 'Subject: ' + bulletin_subject + '\n'
					bulletin_file_content += 'Message:\n\n' + bulletin_message

					print('\tSaving bulletin by:', bulletin_author.encode('ascii', 'ignore'))

					file_path = dumpDirectory + '/Bulletin ' + str(bulletin_id) + output_text_extension

					bytesToTextFile(bulletin_file_content.encode('utf-8'), file_path)

					# No support for comments here. I couldn't find any course that had them.

def processProjectBulletins(institution, pathThusFar, pageURL, session):
	bulletin_response = session.get(pageURL, allow_redirects=True)
	bulletin_document = fromstring(bulletin_response.text)

	dumpDirectory = pathThusFar + '/Bulletins'
	dumpDirectory = makeDirectories(dumpDirectory)

	bulletin_elements = bulletin_document.find_class('newsitem')

	for index, bulletin_element in enumerate(bulletin_elements):

		bulletin_subject = convert_html_content(bulletin_element[0].text_content()).strip()
		bulletin_message = convert_html_content(etree.tostring(bulletin_element[1], encoding='utf-8').decode('utf-8')).strip()
		bulletin_author = convert_html_content(bulletin_element[2][0][0].text_content()).strip()
		bulletin_post_date = convert_html_content(bulletin_element[2][0][1].text_content()).strip()

		bulletin_file_content = 'Author: ' + bulletin_author + '\n'
		bulletin_file_content += 'Posted on: ' + bulletin_post_date + '\n'
		bulletin_file_content += 'Subject: ' + bulletin_subject + '\n'
		bulletin_file_content += 'Message:\n\n' + bulletin_message

		print('\tSaving bulletin by:', bulletin_author.encode('ascii', 'ignore'))

		file_path = dumpDirectory + '/Bulletin ' + str(index + 1) + output_text_extension

		bytesToTextFile(bulletin_file_content.encode('utf-8'), file_path)

def list_courses_or_projects(institution, session, list_page_url, form_string, url_column_index, item_name):
	course_list_response = session.get(list_page_url[institution], allow_redirects = True)
	course_list_page = fromstring(course_list_response.text)
	course_list_form = course_list_page.forms[0]
	
	found_field = False
	for form_field in course_list_form.fields:
		if form_field.startswith(form_string):
			course_list_form.fields[form_field] = 'All'
			found_field = True

	if not found_field:
		print('The script was not able to select all {}. Would you like to continue and only download the {} marked as favourite or active?'.format(item_name.encode('ascii', 'ignore'), item_name.encode('ascii', 'ignore')))
		print('Type "continue" to only download active or favourited {}. Otherwise, the script will abort.'.format(item_name.encode('ascii', 'ignore')))
		decision = input('Continue? ')
		if not decision == 'continue':
			print('Download aborted.')
			sys.exit(0)

	if found_field:
		course_list_dict = convert_lxml_form_to_requests(course_list_form)

	# Part 2: Show all courses

		all_courses_response = session.post(list_page_url[institution], data=course_list_dict, allow_redirects = True)
		all_courses_page = fromstring(all_courses_response.text)

	else:
		# Just use the page we received instead
		all_courses_page = course_list_page

	# Part 3: Extract the course names

	courseList = []
	courseNameDict = {}

	pages_remaining = True
	while pages_remaining:
		courseTableDivElement = None
		for index, entry in enumerate(all_courses_page.find_class('tablelisting')):
			try:
				# The course table has a big div element, and a specific number of headers
				# The latter is a necessity due to the possibility of project invitations
				if len(entry) > 0 and len(entry[0]) > 0 and len(entry[0][0]) > 4:
					courseTableDivElement = entry
					break
			except Exception:
				pass
		if courseTableDivElement is None:
			raise Exception('Failed to locate the course list!')
		
		courseTableElement = courseTableDivElement[0]
		if len(courseTableElement) == 2 and len(courseTableElement[1]) == 1:
			# Table is empty
			pages_remaining = False
			continue
		for index, courseTableRowElement in enumerate(courseTableElement.getchildren()):
			if index == 0:
				continue
			# Extract the course ID from the URL
			courseURL = courseTableRowElement[url_column_index][0].get('href').split("=")[1]
			courseList.append(courseURL)
			courseNameDict[courseURL] = courseTableRowElement[url_column_index][0][0].text
		pages_remaining, course_page_response = loadPaginationPage(list_page_url[institution], all_courses_page, 5)
		if pages_remaining:
			all_courses_page = fromstring(course_page_response.text)

	return courseList, courseNameDict

def dump_courses_or_projects(institution, session, pathThusFar, itemList, itemNameDict, item_type):
	for courseIndex, courseURL in enumerate(itemList):
		try:
			print('Dumping {} with ID {} ({} of {}): {}'.format(item_type, courseURL, (courseIndex + 1), len(itemList), itemNameDict[courseURL].encode('ascii', 'ignore')))
			if courseIndex + 1 < skip_to_course_with_index:
				continue
			if catch_up_directions is not None and courseIndex + 1 < catch_up_directions[0]:
				continue

			locationType = {'course': 1, 'project': 2}[item_type]

			course_response = session.get(itslearning_course_base_url[institution].format(courseURL, locationType), allow_redirects=True)

			root_folder_url_index = course_response.text.find(itslearning_folder_base_url[institution])
			root_folder_end_index = course_response.text.find("'", root_folder_url_index + 1)
			root_folder_url = course_response.text[root_folder_url_index:root_folder_end_index]

			if item_type == 'course':
				course_folder = pathThusFar + '/' + sanitiseFilename(itemNameDict[courseURL])
				bulletin_url = itslearning_course_bulletin_base_url[institution]
			elif item_type == 'project':
				course_folder = pathThusFar + '/Projects/' + sanitiseFilename(itemNameDict[courseURL])
				bulletin_url = itslearning_project_bulletin_base_url[institution]

			try:
				if item_type == 'course':
					processBulletins(institution, course_folder, bulletin_url + courseURL, session, courseURL)
				elif item_type == 'project':
					processProjectBulletins(institution, course_folder, bulletin_url.format(courseURL), session)
			except Exception:
				print('\n\nSTART OF ERROR INFORMATION\n\n\n\n')
				traceback.print_exc()
				print('\n\n\n\nEND OF ERROR INFORMATION')
				print()
				print('Oh no! The script crashed while trying to download Bulletin messages!')
				print('{}, ID {}, item {} of {}'.format(itemNameDict[courseURL].encode('ascii', 'ignore'), courseURL, (courseIndex + 1), len(itemList)))
				print('Some information regarding the error is shown above (see the lines marked with (..) ERROR INFORMATION (..) ).')
				print('Please mail a screenshot of this information to bart.van.blokland@ntnu.no, and I can see if I can help you fix it.')
				print('Would you like to skip the bulletin messages of this {} and move on to the {} contents?'.format(item_type, item_type))
				print('Type \'skip\' if you\'d like to skip the bulletin messages and continue downloading any remaining ones, or anything else if you\'d like to abort the download.'.format(item_type))
				decision = input('Skip this {}? '.format(item_type))
				if decision != 'skip':
					print('Download has been aborted.')
					sys.exit(0)


			processFolder(institution, course_folder, root_folder_url, session, courseIndex, catch_up_state=catch_up_directions)
		except Exception as e:
			print('\n\nSTART OF ERROR INFORMATION\n\n\n\n')
			traceback.print_exc()
			print('\n\n\n\nEND OF ERROR INFORMATION')
			print()
			print('Oh no! The script crashed while trying to download the following {}:'.format(item_type))
			print('{}, ID {}, item {} of {}'.format(itemNameDict[courseURL].encode('ascii', 'ignore'), courseURL, (courseIndex + 1), len(itemList)))
			print('Some information regarding the error is shown above (see the lines marked with (..) ERROR INFORMATION (..) ).')
			print('Please mail a screenshot of this information to bart.van.blokland@ntnu.no, and I can see if I can help you fix it.')
			print('Would you like to skip this {} and move on to the next one?'.format(item_type))
			print('Type \'skip\' if you\'d like to skip this {} and continue downloading any remaining ones, or anything else if you\'d like to abort the download.'.format(item_type))
			decision = input('Skip this {}? '.format(item_type))
			if decision != 'skip':
				print('Download has been aborted.')
				sys.exit(0)















# --- MAIN PROGRAM ---

catch_up_directions = None
if os.path.exists(progress_file_location) and not args.do_listing:
	print('It appears you have run this script previously. Would you like to continue where you left off?')
	print('Type "continue" to fast-forward to where you left off. Type anything else to start over.')
	decision = input('Confirm fast-forward: ')
	if decision == 'continue':
		print('Loading saved state file.')
		with open(progress_file_location) as input_file:
			file_contents = input_file.readlines() 
		state_course_id = int(file_contents[0])
		state_folder_state = [int(i) for i in file_contents[1].split(', ')]
		catch_up_directions = [state_course_id, state_folder_state]

with requests.Session() as session:
	response = session.get(innsida, allow_redirects=True)

	session.get(platform_redirection, allow_redirects=True)

	login_page = fromstring(response.text)

	login_form = login_page.forms[0]

	credentials_correct = False
	if args.username is None:
		print()
		print('----------')
		print('To continue, the script needs your HKR login credentials.')
		print('To do so, type in your HKR username, press Enter, then type in your password, and press Enter again.')
		print()
		print('NOTE: when the program asks for your password, for your security the characters you type are hidden.')
		print('Just type in your password as you normally would, and press Enter.')
		print()

	is_first_iteration = True
	while not credentials_correct:
		if (args.username is None or not is_first_iteration) or (args.password is None or not is_first_iteration):
			print('Please enter your HKR username and password.')

		if args.username is None or not is_first_iteration:
			username = input('Username: ')
		else:
			username = args.username
		if args.password is None or not is_first_iteration:
			password = getpass.getpass(prompt='Password: ')
		else:
			password = args.password

		login_form_dict = convert_lxml_form_to_requests(login_form)
		login_form_dict['ctl00$ContentPlaceHolder1$Username$input'] = username
		login_form_dict['ctl00$ContentPlaceHolder1$Password$input'] = password
		login_form_dict['ctl00$ContentPlaceHolder1$showNativeLoginValueField'] = ""
		login_form_dict['ctl00$ContentPlaceHolder1$nativeLoginButton'] = "Logga in"

		print('Sending login data')
		relay_response = session.post(itslearning_root_url['hkr'], data=login_form_dict, allow_redirects=True)
		if not fromstring(relay_response.text).forms[0].action.startswith('./DashboardMenu.aspx'):
			print('Incorrect credentials!')
		else:
			credentials_correct = True

		is_first_iteration = False

	for institution in institutions:
		print('Access detected successfully.')
		print('Accessing It\'s Learning')

		print('Listing courses.')

		# Part 1: Obtain session-specific form

		courseList, courseNameDict = list_courses_or_projects(institution, session, itsleaning_course_list, 'ctl26$ctl00', 2, 'courses')
		
		print('Found {} courses.'.format(len(courseList)))

		print('Listing projects.')

		projectList, projectNameDict = list_courses_or_projects(institution, session, itslearning_all_projects_url, 'ctl28$ctl00', 1, 'projects')

		print('Found {} projects.'.format(len(projectList)))

		# Feature for listing courses and projects which the user has access to. Triggered by a console parameter.
		if args.do_listing:
			print()
			print('The following courses were found:')
			for courseIndex, courseURL in enumerate(courseList):
				print('Course {}: {}'.format(courseIndex + 1, courseNameDict[courseURL].encode('ascii', 'ignore')))
			print()
			print('The following projects were found:')
			for courseIndex, courseURL in enumerate(projectList):
				print('Course {}: {}'.format(courseIndex + 1, projectNameDict[courseURL].encode('ascii', 'ignore')))
			print()
			# Skip past the actual dumping
			continue

		pathThusFar = output_folder_name

		# If it is desirable to skip to a particular course, also skip downloading the messages again
		if skip_to_course_with_index == 0 and catch_up_directions is None and not args.courses_only and not args.projects_only:
			processMessaging(institution, pathThusFar, session)

		if not args.messaging_only and not args.courses_only:
			print('Dumping Projects')
			dump_courses_or_projects(institution, session, pathThusFar, projectList, projectNameDict, 'project')
		
		if not args.messaging_only and not args.projects_only:
			print('Dumping Courses.')
			dump_courses_or_projects(institution, session, pathThusFar, courseList, courseNameDict, 'course')
		


		print('All content from the institution site was downloaded successfully!')
	print('Done. Everything was downloaded successfully!')
	input('Press Enter to exit.')



	
