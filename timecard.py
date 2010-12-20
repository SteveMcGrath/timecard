#!/usr/bin/env python

import httplib
import urllib
import datetime
import sqlite3
import cmd
import sys
import os
from BeautifulSoup import BeautifulSoup as bsoup

motd = '''
TimeCard Bridge Version 0.1
---------------------------
  Written By: Steven McGrath
Build Number: 032

Copyright (c) 2010 Steven McGrath, All Rights Reserved
---------------------------
for a list of commands, type help.
'''

class TimeCardAPI(object):
  departments = {}
  projects    = {}
  def __init__(self, username, password, host, employee_id):
    self.username     = username
    self.password     = password
    self.host         = host
    self.employee_id  = employee_id
    try:
      cookie            = self.login()
      self.get_data(cookie)
    except:
      print '[!] ERROR: Coulld not connect to Time Card System!'
      print '           Please change your settings and restart.'
  
  def get_cookie(self):
    http = httplib.HTTPSConnection(self.host)
    http.request('GET', '/atrweb/')
    resp = http.getresponse()
    cookie = resp.getheader('set-cookie').split(';')[0]
    cookie += '; Language=; Languages=; Remember%5Fme=; Password=; Login=;'
    return cookie
  
  def login(self):
    cookie = self.get_cookie()
    http = httplib.HTTPSConnection(self.host)
    payload = urllib.urlencode({
         'Login': self.username,
      'Password': self.password,
      'Language': 0,
          'Type': 0
    })
    headers = {
              'Cookie': cookie,
      'Content-Length': len(payload),
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    http.request('POST', '/atrweb/Default.asp?Action=Login', payload, headers)
    resp    = http.getresponse()
    return cookie
  
  def get_data(self, cookie):
    http = httplib.HTTPSConnection(self.host)
    headers = {'Cookie': cookie}
    http.request('GET', '/atrweb/DayInfo.asp?adtmDate=%s' %\
                        datetime.datetime.now().strftime('%d/%m/%Y'), headers=headers)
    resp = http.getresponse()
    page = bsoup(resp.read())
        
    # Parse out the depaerment listing...
    departments = page.find('select', {'name': 'ddl_abbr'})
    for department in departments.findChildren():
      try:
        val = int(department.get('value'))
      except:
        continue
      self.departments[val] = department.text
    
    # Parse some disgusting Javascript for the projects and tasks:
    html = page.prettify()
    text_pos  = html.find('Np=new Array(')
    text_list = html[text_pos:text_pos+3000].split('\r')[0].strip('Np=new Array(').strip(');').split('","')
    val_pos   = html.find('Kp=new Array(')
    val_list  = html[val_pos:val_pos+3000].split('\r')[0].strip('Kp=new Array(').strip(');').split('","')
    task_pos  = html.find('TaskArray = new Array(')
    task_list = html[task_pos:task_pos+10000].split('\n')[0].strip('TaskArray = new Array(').strip('))').split('),new Array(')
    for entry in val_list:
      try:
        value = int(entry.strip('"'))
        if entry is not 'Error!':
          self.projects[value] = {'tasks': {}}
          self.projects[value]['value'] = text_list[val_list.index(entry)].strip('"')
          for item in task_list:
            dset  = item.split(',')
            proj  = int(dset[0])
            name  = dset[1]
            val   = int(dset[2])
            if proj == value:
              self.projects[value]['tasks'][val] = name.strip('\'')
      except ValueError:
        continue
    
    return page
  
  def entry(self, description, time_from, time_to, department, project, task, notes='', is_billable=False, code=''):
    cookie    = self.login()
    #if code != '':
    #  valid_values = ['Budgeted', 'NonBud', 'Planned', 'Not Planned']
    #  if code not in valid_values:
    #    raise 'Bad code, must be one of %s' % valid_values
    payload   = {
         'selected_row': '',
       'operating_code': 0,
            'timing_id': 0,
          'strings_num': 0,
      'int_employee_id': self.employee_id,
             'dtm_date': time_from.strftime('%m/%d/%Y'),
                'notes': '',
             'ddl_abbr': department,
          'ddl_project': project,
                'tasks': task,
          'date_from_f': time_from.strftime('%m/%d/%Y'),
             'dtm_from': time_from.strftime('%H:%M'),
            'date_to_f': time_to.strftime('%m/%d/%Y'),
               'dtm_to': time_to.strftime('%H:%M'),
      'txt_description': description,
            'txt_notes': notes,
                'save1': 'Save',
            'ddl_IN_ON': code,
          'is_billable': int(is_billable),
                 'link': 1,
    }
    
    form      = urllib.urlencode(payload)
    headers   = {
              'Cookie': cookie,
      'Content-Length': len(form),
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    
    http      = httplib.HTTPSConnection(self.host)
    http.request('POST', '/atrweb/operate.asp', form, headers)
    response  = http.getresponse()
    #if response.getheader('location') == './Error.asp':
    #print '--- REQUEST ---'
    #print 'Cookie: ' + cookie
    #print '-- Payload --'
    #for item in payload:
    #  print '%20s: %s' % (item, payload[item])
    #print form
    #print '--- RESPONSE ---'
    #print response.getheaders()
    #print response.read()


class Database(object):
  def __init__(self, filename):
    self.db = sqlite3.connect(filename)
    check   = self.sql('SELECT * FROM sqlite_master')
    if len(check) < 1:
      self.build_db()
  
  def sql(self, query):
    cursor  = self.db.execute(query)
    return cursor.fetchall()
  
  def build_db(self):
    self.db.executescript('''
      CREATE TABLE time_entry (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        start_time  DATETIME,
        end_time    DATETIME,
        billable    BOOLEAN,
        department  TEXT,
        project     TEXT,
        task        TEXT,
        description TEXT,
        notes       TEXT
      );
      
      CREATE TABLE settings (
        name        TEXT PRIMARY KEY,
        value       TEXT
      );
      
      CREATE TABLE templates (
        name        TEXT PRIMARY KEY,
        billable    BOOLEAN,
        department  TEXT,
        project     TEXT,
        task        TEXT,
        description TEXT,
        notes       TEXT
      );
      
      INSERT INTO settings VALUES ('username', '');
      INSERT INTO settings VALUES ('password', '');
      INSERT INTO settings VALUES ('host', '');
      INSERT INTO settings VALUES ('employee_id', '');
      INSERT INTO settings VALUES ('department', '');
    ''')
  
  def add_entry(self, start_time, end_time, billable, department, project, 
                task, description, notes):
    self.sql('''
      INSERT INTO time_entry
             (start_time, end_time, billable, department, project, task,
             description, notes)
      VALUES (datetime('%s'),datetime('%s'),'%s','%s','%s','%s','%s','%s')
    ''' % (start_time.strftime('%Y-%m-%d %H:%M:%S'), 
           end_time.strftime('%Y-%m-%d %H:%M:%S'), 
           billable, department, project, task, description, notes))
  
  def get_day(self, date):
    return self.sql('''
      SELECT *
        FROM time_entry
       WHERE date(start_time) = date('%s')
       ORDER BY start_time DESC
    ''' % date.strftime('%Y-%m-%d'))
  
  def get_entry(self, entry_id):
    return self.sql('''
      SELECT *
        FROM time_entry
       WHERE id = '%s'
    ''' % entry_id)
  
  def set_setting(self, name, value):
    return self.sql('''
      INSERT OR REPLACE INTO settings
      VALUES ('%s','%s')
    ''' % (name, value))
  
  def get_setting(self, name):
    return self.sql('''
      SELECT value
        FROM settings
       WHERE name = '%s'
    ''' % name)[0][0]
  
  def get_templates(self):
    return self.sql('''
      SELECT *
        FROM templates
    ''')
  
  
  
  def add_template(self, name, billable, dept, project, task, desc, notes):
    return self.sql('''
      INSERT OR REPLACE INTO templates
      VALUES('%s','%s','%s','%s','%s','%s','%s')
    ''' % (name, billable, dept, project, task, desc, notes))
  
  def format_entry(self, db_entry):
    return {
      'entry_id': int(db_entry[0]),
         'start': self.__date(db_entry[1]),
        'finish': self.__date(db_entry[2]),
      'billable': bool(db_entry[3]),
    'department': int(db_entry[4]),
       'project': int(db_entry[5]),
          'task': int(db_entry[6]),
   'description': db_entry[7],
         'notes': db_entry[8],
    }
  
  def add_entry_dict(self, entry):
    self.add_entry(entry['start'], entry['finish'], entry['billable'],
                   entry['department'], entry['project'], entry['task'],
                   entry['description'], entry['notes'])
  
  def remove_entry(self, entry_id):
    self.sql('''
      DELETE FROM time_entry WHERE id = '%s'
    ''' % entry_id)
  
  def commit(self):
    self.db.commit()
  
  def close(self):
    self.db.close()
  
  def __date(self, entry):
    date  = entry.split()[0].split('-')
    time  = entry.split()[1].split(':')
    return datetime.datetime(int(date[0]),
                             int(date[1]),
                             int(date[2]),
                             int(time[0]),
                             int(time[1]),
                             int(time[2]))


class TimeCardCLI(cmd.Cmd):
  intro   = motd
  db      = Database('%s/.timecard.sqlite3' % os.environ['HOME'])
  api     = TimeCardAPI(db.get_setting('username'),
                        db.get_setting('password'),
                        db.get_setting('host'),
                        db.get_setting('employee_id'))
  dept    = db.get_setting('department')
  prompt  = 'timecard(%s)> ' % db.get_setting('username')
  
  def do_set(self, s):
    '''
    set [name] [value]
    Updates a setting.
    
    Available settings:
    username        Username for TimeCard System
    password        Password for TimeCard System
    host            Hostname of the TimeCard System
    employee_id     Employee ID for TimeCard System
    department      Default Department for Entries
    '''
    name  = s.split()[0]
    value = s.split()[1]
    self.db.set_setting(name, value)
  
  def do_get(self, name):
    '''
    get [name]
    Retrieves a setting.
    
    Available settings:
    username        Username for TimeCard System
    password        Password for TimeCard System
    host            Hostname of the TimeCard System
    employee_id     Employee ID for TimeCard System
    department      Default Department for Entries
    '''
    print self.db.get_setting(name)
  
  def do_add(self, s):
    '''
    entry [date=YYYY-MM-DD] [billable=BOOL] [dept=ID] [temp=SAVE]
          [start_time] [end_time] [project_id] task_id]
    
    NOTES: Templating is not active yet.
    '''
    entry       = s.strip().split()
    billable    = False
    department  = self.dept
    date        = datetime.date.today()
    tc_entry    = {}
    try:
      for item in entry:
        dset = item.split('=')
        if len(dset) > 1:
          if dset[0] == 'date':
            parsed    = dset[1].split('-')
            date      = datetime.date(int(parsed[0]), 
                                      int(parsed[1]), 
                                      int(parsed[2]))
          if dset[0] == 'billable':
            billable = bool(dset[1])
          if dset[0] == 'dept':
            department = int(dset[1])
          entry.pop(entry.index(item))
      stime     = entry[0].split(':')
      ftime     = entry[1].split(':')
      tc_entry['start']       = datetime.datetime(date.year, date.month, 
                                   date.day, int(stime[0]), int(stime[1]))
      tc_entry['finish']      = datetime.datetime(date.year, date.month, 
                                   date.day, int(ftime[0]), int(ftime[1]))
      tc_entry['billable']    = int(billable)
      tc_entry['department']  = department
      tc_entry['project']     = int(entry[2])
      tc_entry['task']        = int(entry[3])   
      tc_entry['description'] = raw_input('Enter Description : ')
      tc_entry['notes']       = raw_input('      Enter Notes : ')
      self.db.add_entry_dict(tc_entry)
    except:
      print 'Invalid Input'
  
  def do_list(self, s):
    '''
    list [category] [id]
    Retreives the list of values for a given category.
    '''
    category  = s.split()[0]
    if len(s.split()) > 1:
      pid     = int(s.split()[1])
    else:
      pid     = None
    
    if category == 'departments':
      for item in self.api.departments:
        print '%10s\t\t\t%s' % (item, self.api.departments[item])
    if category == 'projects':
      for item in self.api.projects:
        if item != 'Error!':
          if pid is not None:
            if item != pid:
              continue
          print '%10s\t\t%s' % (item, self.api.projects[item]['value'])
          tasks = self.api.projects[item]['tasks']
          for entry in tasks:
            print '\t%10s\t\t%s' % (entry, tasks[entry])
  
  def do_search(self, s):
    '''
    search [string]
    Searches departments, projects, and tasks for a match and displays the
    resulting codes.
    '''
    print 'Departmental Matches'
    print '--------------------'
    for entry in self.api.departments:
      if self.api.departments[entry].lower().find(s) > -1:
        print '[%4s] %s' % (entry, self.api.departments[entry])
    
    print 'Project and Task Matches'
    for project in self.api.projects:
      disp = False
      if self.api.projects[project]['value'].lower().find(s) > -1:
        print '[%4s] %s' % (project, self.api.projects[project]['value'])
        disp = True
      for task in self.api.projects[project]['tasks']:
        if self.api.projects[project]['tasks'][task].lower().find(s) > -1 or\
           disp == True:
          print '\t[%4s, %4s] %s / %s' % (project, task,
                                    self.api.projects[project]['value'],
                                    self.api.projects[project]['tasks'][task])
  
  def do_commit(self, s):
    '''
    commit
    Forces a commit of the local database
    '''
    self.db.commit()
  
  def do_push(self, s):
    '''
    push [date=DATE|entry=ENTRY]
    Sends the specified day's entries to the Time Card system.  By default
    it will send today's entries.
    '''
    if len(s) < 5:
      entry_type  = 'date'
      entry_value = datetime.date.today().strftime('%Y-%m-%d')
    else:
      dset        = s.strip().split('=')
      entry_type  = dset[0]
      entry_value = dset[1]
      
    if entry_type == 'date':
      parsed    = entry_value.split('-')
      date      = datetime.date(int(parsed[0]), 
                                int(parsed[1]), 
                                int(parsed[2]))
      for db_entry in self.db.get_day(date):
        entry   = self.db.format_entry(db_entry)
        self.api.entry(entry['description'],
                           entry['start'],
                           entry['finish'],
                           entry['department'],
                           entry['project'],
                           entry['task'],
                           notes=entry['notes'],
                           is_billable=entry['billable'])
        print '[*] Pushed up entry %s' % entry['entry_id']
    if entry_type == 'entry':
      entry = self.db.format_entry(self.db.get_entry(entry_value))
      self.api.entry(entry['description'],
                         entry['start'],
                         entry['finish'],
                         entry['department'],
                         entry['project'],
                         entry['task'],
                         notes=entry['notes'],
                         is_billable=entry['billable'])
      print '[*] Pushed up entry %s' % entry['entry_id']
      
  def do_show(self, s):
    '''
    show [date=YYYY-MM-DD|entry=ENTRY]
    Displays entries.'
    '''
    if len(s) < 5:
      entry_type  = 'date'
      entry_value = datetime.date.today().strftime('%Y-%m-%d')
    else:
      dset        = s.strip().split('=')
      entry_type  = dset[0]
      entry_value = dset[1]
    
    print 'ID    BIL DATE       START FINISH DEPARTMENT                     PROJECT                        TASK                                     DESCRIPTION'
    print '----- --- ---------- ----- ------ ------------------------------ ------------------------------ ---------------------------------------- --------------------------------'
    if entry_type == 'date':
      parsed    = entry_value.split('-')
      date      = datetime.date(int(parsed[0]), 
                                int(parsed[1]), 
                                int(parsed[2]))
      for db_entry in self.db.get_day(date):
        entry   = self.db.format_entry(db_entry)
        print '%-5s %-3s %-10s %-5s %-6s %-25s%5s %-25s%5s %-35s%5s %s' %\
              (entry['entry_id'], int(entry['billable']), 
               entry['start'].strftime('%Y-%m-%d'),
               entry['start'].strftime('%H:%M'),
               entry['finish'].strftime('%H:%M'),
               self.api.departments[entry['department']],
               '[%s]' % entry['department'],
               self.api.projects[int(entry['project'])]['value'],
               '[%s]' % entry['project'],
               self.api.projects[int(entry['project'])]['tasks'][int(entry['task'])],
               '[%s]' % entry['task'],
               entry['description']
               )
        #if entry['description'] != '':
        #  print '\t\t\t\t\tDESCRIPTION: %s' % entry['description']
        if entry['notes'] != '':
          print '\t\t\t\t\t      NOTES: %s' % entry['notes']
  
  def do_del(self, s):
    '''
    del [entry id]
    Deletes an entry from the database.
    '''
    self.db.remove_entry(int(s))
  
  def do_template(self, s):
    '''
    template [name] [department] [project] [task] [billable]
    '''
    pass
  
  def do_dump(self, s):
    print self.api.departments
    print self.api.projects
  
  def do_exit(self, s):
    '''
    Exits the timecard script.
    '''
    self.db.commit()
    self.db.close()
    sys.exit(0)
    

if __name__ =='__main__':  
  if len(sys.argv) > 1:
      TimeCardCLI().onecmd(' '.join(sys.argv[1:]))
  else:
      TimeCardCLI().cmdloop()