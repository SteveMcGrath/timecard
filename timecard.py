#!/usr/bin/env python

import httplib
import urllib
import datetime
import os
import sys
import getopt
import cmd
from ConfigParser               import ConfigParser
from BeautifulSoup              import BeautifulSoup    as bsoup
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy                 import Table, Column, Integer, String, Time, \
                                       DateTime, Date, ForeignKey, Text,     \
                                       Boolean, create_engine, MetaData,     \
                                       and_, or_
from sqlalchemy.orm             import relationship, backref, sessionmaker

Base            = declarative_base()

motd = '''TimeCard PoC Version 2 Build 8
BUGS/ISSUES:
  * Options must be specified before any arguments are set.
  * Not all of the code has been fully baked.  Please report any issues to the
    github repository.
  * Documentation needs to be improved.
  * Code needs a massive cleanup.
'''

default_config = '''
[General]
# The following option sets the default department used.  This is meant to be
# a shotcut for people that are entering the majority of their time into the
# same department.  Note that this needs to be an integer.
default_department = 0

[ATR]
# This is your ATRWeb Username
username = USERNAME

# This is your ATRWeb Password
password = PASSWORD

# This is the hostname of ATR.
host = infrastructuretime

# Is the ATRWeb environment we are connecting to SSL enabled?
ssl = yes

# This is the Employee id (sel_names) that ATR uses internally.  This number
# can be found if you login to the site, then goto a specific day and look at
# the URL.  you should see a sel_names (or similar) part of the URL with a
# number associated with it.  That number is what you will need to put here.
employee_id = 0
'''

class Department(Base):
  __tablename__ = 'department'
  id            = Column(Integer, primary_key=True)
  name          = Column(Text)

class Project(Base):
  __tablename__ = 'project'
  id            = Column(Integer, primary_key=True)
  name          = Column(Text)
  tasks         = relationship('Task', backref='project')

class Task(Base):
  __tablename__ = 'task'
  id            = Column(Integer, primary_key=True)
  project_id    = Column(Integer, ForeignKey('project.id'))
  name          = Column(Text)

class Template(Base):
  __tablename__ = 'template'
  id            = Column(Integer, primary_key=True)
  name          = Column(Text)
  description   = Column(Text)

class Action(Base):
  __tablename__ = 'action'
  id            = Column(Integer, primary_key=True)
  stack         = Column(Integer)
  duration      = Column(Integer)
  template_id   = Column(Integer, ForeignKey('template.id'))
  department_id = Column(Integer, ForeignKey('department.id'))
  project_id    = Column(Integer, ForeignKey('project.id'))
  task_id       = Column(Integer, ForeignKey('task.id'))
  template      = relationship('Template', backref='actions', order_by='Action.stack')
  department    = relationship('Department', backref='actions')
  project       = relationship('Project', backref='actions')
  task          = relationship('Task', backref='actions')
  billable      = Column(Boolean)
  description   = Column(Text)
  notes         = Column(Text)
  
  def gen_entry(self, t, values):
    desc    = self.description
    notes   = self.notes
    for item in values:
      desc  = desc.replace('{%s}' % item, values[item])
      notes = notes.replace('{%s}' % item, values[item])
    entry               = TimeEntry()
    entry.date          = datetime.date(t.year, t.month, t.day)
    entry.start_time    = datetime.time(t.hour, t.minute)
    entry.end_time      = (datetime.datetime(t.year, t.month, t.day ,
                                             t.hour, t.minute) +\
                          datetime.timedelta(minutes=self.duration)).time()
    entry.billable      = self.billable
    entry.department_id = self.department_id
    entry.project_id    = self.project_id
    entry.task_id       = self.task_id
    entry.description   = desc
    entry.notes         = notes
    return entry
    

class TimeEntry(Base):
  __tablename__ = 'entry'
  id            = Column(Integer(6), primary_key=True)
  date          = Column(Date)
  start_time    = Column(Time)
  end_time      = Column(Time)
  billable      = Column(Boolean)
  department_id = Column(Integer, ForeignKey('department.id'))
  project_id    = Column(Integer, ForeignKey('project.id'))
  task_id       = Column(Integer, ForeignKey('task.id'))
  department    = relationship('Department', backref='entries')
  project       = relationship('Project', backref='entries')
  task          = relationship('Task', backref='entries')
  billable      = Column(Boolean)
  description   = Column(Text)
  notes         = Column(Text)

class TimeCardAPI(object):
  cookie = None
  
  def __init__(self, username, password, host, employee_id, ssl=False):
    '''
    __init__(username, password, host, employee_id, ssl=False)
    Initializes the TimeCardAPI object.  Most of the fields should be self
    explanatory however ther employee_id is derrived form the sel_names
    variable found in the URL of some pages.  find this number and we will
    use that.
    '''
    self.username     = username
    self.password     = password
    self.host         = host
    self.employee_id  = employee_id
    if ssl:
      self.con        = httplib.HTTPSConnection
    else:
      self.con        = httplib.HTTPConnection
  
  def _set_cookie(self, resp):
    '''
    Pulls out the session cookie from the http response.
    '''
    cookie  = resp.getheader('set-cookie').split(';')[0]
    cookie += '; Language=; Languages=; Remember%5Fme=; Password=; Login=;'
    self.cookie = cookie
  
  def _post(self, url, payload, cookie_update=False):
    '''
    General HTTP post function.  Requires a url and a payload.
    '''
    body    = urllib.urlencode(payload)
    headers = {
            'Cookie': self.cookie,
    'Content-Length': len(body),
      'Content-Type': 'application/x-www-form-urlencoded'
    }
    http    = self.con(self.host)
    http.request('POST', url, body, headers)
    resp    = http.getresponse()
    page    = bsoup(resp.read())
    if cookie_update:
      self._set_cookie(resp)
    return page
  
  def _get(self, url, cookie_update=False):
    '''
    General HTTP Get function.  Requires a URL.
    '''
    if cookie_update:
      self.cookie = ''
    headers = {'Cookie': self.cookie,}
    http    = self.con(self.host)
    http.request('GET', url, headers=headers)
    resp    = http.getresponse()
    page    = bsoup(resp.read())
    if cookie_update:
      self._set_cookie(resp)
    return page
  
  def login(self):
    '''
    Runs the series of posts and gets in order to log the user in with the
    session cookie that we have.
    '''
    self._get('/atrweb/', cookie_update=True)
    self._post('/atrweb/Default.asp?Action=Login', {
         'Login': self.username,
      'Password': self.password,
      'Language': 0,
          'Type': 0,
    })
  
  def pull_database(self):
    '''
    Pulls down the database entries needed to populate the department,
    project, and task tables.
    '''
    self.login()
    cur_date  = datetime.datetime.now().strftime('%d/%m/%Y')
    page      = self._get('/atrweb/DayInfo.asp?adtmDate=%s' % cur_date)
    db        = {'departments': {}, 'projects': {}}
    
    # First thing we need to do is pull the departments.  This is actually the
    # easier of the tasks at hand as they are stored in a pretty nice and
    # easy format to parse.
    return page
    deps      = page.find('select', {'name': 'ddl_abbr'})
    for dep in deps.findChildren():
      try:
        val     = int(dep.get('value'))
        db['departments'][val] = dep.text
      except:
        pass
    
    # Now for the fun part.  We need to parse some pretty grotesque javascript
    # in order to pull out the dictionaries that we need to parse. to do this
    # we need to actually convert the page back to a srting and try to handle
    # it that way.
    html  = page.prettify()
    dpos  = html.find('Np=new Array(')
    vpos  = html.find('Kp=new Array(')
    tpos  = html.find('TaskArray = new Array(')
    dlist = html[dpos:dpos+3000].split('\r')[0].strip('Np=new Array(').strip(');').split('","')
    vlist = html[vpos:vpos+3000].split('\r')[0].strip('Kp=new Array(').strip(');').split('","')
    tlist = html[tpos:tpos+10000].split('\n')[0].strip('TaskArray = new Array(').strip('))').split('),new Array(')
    
    # Now that we have all the data parsed out (hopefully) we need to try to
    # peice it back together into something meaningful.  This is some more
    # nasty hackery and I apologise in advance.
    for entry in vlist:
      try:
        if entry is not 'Error!':
          val = int(entry.strip('"'))
          db['projects'][val] = {
            'tasks': {},
            'value': dlist[vlist.index(entry)].strip('"')
          }
          for item in tlist:
            dset  = item.split(',')
            proj  = int(dset[0])
            name  = dset[1].strip('\'')
            value = int(dset[2])
            if proj == val:
              db['projects'][val]['tasks'][value] = name
      except ValueError:
        continue
    return db
  
  def add(self, entry):
    '''
    Adds a TimeEntry object into ATRWeb.
    '''
    payload = {
       'selected_row': '',
     'operating_code': 0,
          'timing_id': 0,
        'strings_num': 0,
    'int_employee_id': self.employee_id,
           'dtm_date': entry.date.strftime('%m/%d/%Y'),
              'notes': '',
           'ddl_abbr': entry.department.id,
        'ddl_project': entry.project.id,
              'tasks': entry.task.id,
        'date_from_f': entry.date.strftime('%m/%d/%Y'),
           'dtm_from': entry.start_time.strftime('%H:%M'),
          'date_to_f': entry.date.strftime('%m/%d/%Y'),
             'dtm_to': entry.end_time.strftime('%H:%M'),
    'txt_description': entry.description,
          'txt_notes': entry.notes,
              'save1': 'Save',
          'ddl_IN_ON': '',
        'is_billable': entry.billable,
               'link': 1,
    }
    self._post('/atrweb/operate.asp', payload)

class TimeCardCLI(cmd.Cmd):
  config  = ConfigParser()
  intro   = motd
  
  def __init__(self):
    cloc        = os.path.join(sys.path[0], 'config.ini')
    if not os.path.exists(cloc):
      config = open(cloc, 'w')
      config.write(default_config)
      print 'Please change the configuration options in the config file\n' +\
            'located at %s before continuing' % cloc
      sys.exit()
    self.config.read(cloc)
    self.prompt = 'tc[%s]> ' % self.config.get('ATR', 'username')
    self.dept   = self.config.getint('General', 'default_department')
    
    sql_string  = 'sqlite:///%s' % os.path.join(sys.path[0],'database.sqlite')
    self.engine = create_engine(sql_string)
    self.smaker = sessionmaker(bind=self.engine)
    Department.metadata.create_all(self.engine)
    Project.metadata.create_all(self.engine)
    Task.metadata.create_all(self.engine)
    Template.metadata.create_all(self.engine)
    Action.metadata.create_all(self.engine)
    TimeEntry.metadata.create_all(self.engine)
    
    self.api    = TimeCardAPI(self.config.get('ATR', 'username'),
                              self.config.get('ATR', 'password'),
                              self.config.get('ATR', 'host'),
                              self.config.get('ATR', 'employee_id'),
                              self.config.getboolean('ATR', 'ssl'))
    cmd.Cmd.__init__(self)
  
  def _print_department(self, department):
    '''
    Private Function:  Prints a department to the screen.
    '''
    print 'D: [%3d] %s' % (department.id, department.name)
  
  def _print_project(self, project):
    '''
    Private Function:  Prints a project and all associated tasks to the screen.
    '''
    print 'P: [%3d] %s' % (project.id, project.name)
    for task in project.tasks:
      self._print_task(task)
  
  def _print_task(self, task):
    '''
    Private Function:  Prints a task to the screen.
    '''
    print '\t[%3d %3d] %s' % (task.project.id, task.id, task.name)
  
  def _print_template(self, template):
    '''
    Private Function:  Prints a template and all associated actions to the screen.
    '''
    print 'T: [%3d] %s\n\t%s' % (template.id, template.name, 
                                 template.description)
    for action in template.actions:
      print '\t[%3d] %s %s %s %s %s\n\t\t Notes: %s' %\
            (action.id, action.duration, action.department.id, 
             action.project.id, action.task.id, action.description, 
             action.notes)
  
  def _date(self, s):
    try:
      year, month, day = val.split('-')
      return True, datetime.date(int(year), int(month), int(day))
    except:
      return False, 'Invalid Year Argument.  Must be YYYY-MM-DD'
  
  def _time(self, s):
    try:
      hour, minute  = s.split(':')
      return True, datetime.time(int(hour), int(minute))
    except:
      return False, 'Invalid Argument.  Must be HH:MM'
  
  def _int(self, s):
    try:
      return True, int(s)
    except:
      return False, 'Invalid Argument.  Must be an integer.'
      
  
  def do_add(self, s):
    '''add [OPTIONS] [starttime] [endtime] [projectId] [taskId] [description]
    Adds an entry into the local timecard database.
    
     -d (--date) [DATE]       Overrides the date of the entry with the date
                              specified.
     -b (--billable)          Sets the billable flag to true.
     -D (--dept)              Overrides the default department with the
                              department id specified.
    '''
    entry               = TimeEntry()
    date                = datetime.date.today()
    entry.department_id = self.dept
    entry.billable      = False
    
    # First thing we need to see if there are any optional arguments in the
    # line and parse those first.  If there are any we will override the
    # default settings that have already been specified.
    opts, args  = getopt.getopt(s.split(), 'd:bD:', 
                  ['date=', 'billable', 'dept='])
    for opt, val in opts:
      if opt in ('-d', '--date'):
        code, date = self._date(val)
        if not code: print date; return
      if opt in ('-b', '--billable'):
        entry.billable = True
      if opt in ('-D', '--dept'):
        code, did = self._int(val)
        if not code: print did; return
        entry.department_id = did
    
    # Now we are going to setup the entry object.  The try blocks are setup
    # so that if any of the inputs are not what we expect we can tell the
    # user that the entry was no good and then quit out before adding it into
    # the database.
    entry.date = date
    if len(args) >= 4:
      try:
        entry.start_time  = datetime.time(\
                      int(args[0].split(':')[0]), int(args[0].split(':')[1]))
      except:
        print 'Invalid Start Time.  Must be HH:MM.'
        return
      try:
        entry.end_time    = datetime.time(\
                      int(args[1].split(':')[0]), int(args[1].split(':')[1]))
      except:
        print 'Invalid End Time.  Must be HH:MM.'
        return
      try:
        entry.project_id  = int(args[2])
      except:
        print 'Invalid Project id.  Must be integer.'
        return
      try:
        entry.task_id     = int(args[3])
      except:
        print 'Invalid Task id.  Must be ineteger.'
        return
      if len(args) > 4:
        entry.description = ' '.join(args[4:])
      else:
        entry.description = raw_input('Enter Description : ')
      entry.notes         = raw_input('      Enter Notes : ')
      
      #try:
      session = self.smaker()
      session.add(entry)
      session.commit()
      session.close()
      #except:
      #  print 'Could not add the data into the database.  please check to\n'+\
      #        'make there that there are no issues with the data provided.'
    else:
      print 'Not enough arguments.'
  
  def do_search(self, s):
    '''search [OPTIONS] [string]
     -d (--dept)      Tells search to search departments instead.
     -t (--template)  Tells search to search templates instead.
    '''
    criteria = 'projects'
    # First thing we need to see if there are any optional arguments in the
    # line and parse those first.  If there are any we will override the
    # default settings that have already been specified.
    opts, args  = getopt.getopt(s.split(), 'dt', ['template', 'dept'])
    for opt, val in opts:
      if opt in ('-d', '--dept'):
        criteria = 'departments'
      if opt in ('-t', '--template'):
        criteria = 'templates'
    if len(args) > 0:
      search = ' '.join(args)
    else:
      print 'No Search Criteria Specified.'
      return
    session  = self.smaker()
    
    if criteria == 'projects':
      # If we are doin a default search we will first search for any matches
      # in the projects table.  If we do, we will display the matching
      # projects and all of the tasks associated with that project.  IF there
      # are no project matches, then we will degrade to searching the tasks
      # themselves.
      projects = session.query(Project).filter(Project.name.contains(search)).all()
      for project in projects:
        self._print_project(project)
      if len(projects) == 0:
        tasks = session.query(Task).filter(Task.name.contains(search)).all()
        for task in tasks:
          self._print_task(task)
    
    if criteria == 'departments':
      # Here we will simply search through all the available departments and
      # return the matches.
      departments = session.query(Department).filter(Department.name.contains(search)).all()
      for department in departments:
        self._print_department(department)
    
    if criteria == 'templates':
      # Same thing as departments, however we will also print out the actions
      # for each template.
      temps = session.query(Template).filter(or_(\
                      Template.name.contains(search),
                      Template.description.contains(search))).all()
      for temp in temps:
        self._print_template(temp)
  
  def do_list(self, s):
    '''list [OPTIONS]
    Lists all the entries in the database.  By default this will list all of
    the projects (and associated tasks).  You can change this behavior with
    the flags below.
    
     -d (--dept)      Changes the listing to a departmental listing
     -t (--template)  Changes the listing to a template listing
    '''
    session  = self.smaker()
    criteria = 'projects'
    # First thing we need to see if there are any optional arguments in the
    # line and parse those first.  If there are any we will override the
    # default settings that have already been specified.
    opts, args  = getopt.getopt(s.split(), 'dt', ['template', 'dept'])
    for opt, val in opts:
      if opt in ('-d', '--dept'):
        criteria = 'departments'
      if opt in ('-t', '--template'):
        criteria = 'templates'
    
    if criteria == 'projects':
      # If we are doin a default search we will first search for any matches
      # in the projects table.  If we do, we will display the matching
      # projects and all of the tasks associated with that project.  IF there
      # are no project matches, then we will degrade to searching the tasks
      # themselves.
      projects = session.query(Project).all()
      for project in projects:
        self._print_project(project)
      if len(projects) == 0:
        tasks = session.query(Task).filter_by(name=search).all()
        for task in tasks:
          self._print_task(task)

    if criteria == 'departments':
      # Here we will simply search through all the available departments and
      # return the matches.
      departments = session.query(Department).all()
      for department in departments:
        self._print_department(department)

    if criteria == 'templates':
      # Same thing as departments, however we will also print out the actions
      # for each template.
      temps = session.query(Template).all()
      for temp in temps:
        self._print_template(temp)
    
    session.close()
  
  def do_push(self, s):
    '''push [OPTIONS]
    Pushes the local entries up to the ATR timecard system.  Please note that
    if you need to make changes after you have pushed the entries, you will
    need to login to the web system to make the changes, or push the changes
    and then delete the duplicates on the ATR system itself.
    
    Because of this, make sure that you really want to push your entries up
    before you do so.
    
     -d (--date)  [DATE]  Changes the date to the specified date.
     -e (--entry) [ID]    Sets the push type to a single entry and uses the
                          specified id.
     -w (--week) [DATE]   Sets the push type to a whole week and uses the date
                          specified to calculate a week range to pull (Sun-Sat)
    '''
    date    = datetime.date.today()
    entry   = None
    week    = None
    stype   = 'date'
    session = self.smaker()
    # First thing we need to see if there are any optional arguments in the
    # line and parse those first.  If there are any we will override the
    # default settings that have already been specified.
    opts, args  = getopt.getopt(s.split(), 'd:e:w:', 
                                  ['date=', 'entry=', 'week='])
    for opt, val in opts:
      if opt in ('-d', '--date'):
        code, date = self._date(val)
        if not code: print date; return
      if opt in ('-e', '--entry') and stype == 'date':
        stype = 'entry'
        code, entry = self._int(val)
        if not code: print entry; return
      if opt in ('-w', '--week') and stype == 'date':
        stype = 'week'
        start = date - datetime.timedelta(int(date.strftime('%w')))
        end   = start + datetime.timedelta(6)
    
    time_entries = []
    if stype == 'date':
      time_entries = session.query(TimeEntry)\
                        .filter(TimeEntry.date == date).all()
    if stype == 'entry':
      time_entries = session.query(TimeEntry)\
                        .filter_by(id=entry).all()
    if stype == 'week':
      time_entries = session.query(TimeEntry)\
                        .filter(and_(TimeEntry.date >= start,
                                     TimeEntry.date <= end))
    
    try:
      self.api.login()
    except:
      print 'ERROR: Could not talk to host.  check your configuration.'
      return
    for item in time_entries:
      self.api.add(item)
      print 'Pushed Entry Number %s' % item.id
    session.close()
  
  def do_update(self, s):
    '''update
    Updates the Database to current.'''
    session = self.smaker()
    
    self.api.login()
    db = self.api.pull_database()
    for item in db['departments']:
      try:
        dept      = session.query(Department).filter_by(id=item).one()
        dept.name = db['departments'][item]
        session.merge(dept)
        print 'Updating Department: %s' % dept.name
      except:
        dept      = Department()
        dept.id   = item
        dept.name = db['departments'][item]
        session.add(dept)
        print 'Adding Department: %s' % dept.name
    session.commit()
    
    for item in db['projects']:
      try:
        proj      = session.query(Project).filter_by(id=item).one()
        proj.name = db['projects'][item]['value']
        session.merge(proj)
        session.commit()
        print 'Updating Project: %s' % proj.name
      except:
        proj      = Project()
        proj.id   = item
        proj.name = db['projects'][item]['value']
        session.add(proj)
        session.commit()
        print 'Adding Project: %s' % proj.name
      for tid in db['projects'][item]['tasks']:
        try:
          task      = session.query(Task).filter_by(id=tid).one()
          task.project_id = item
          task.name = db['projects'][item]['tasks'][tid]
          session.merge(task)
          session.commit()
          print 'Updating Task: %s' % task.name
        except:
          task      = Task()
          task.id   = tid
          task.project_id = item
          task.name = db['projects'][item]['tasks'][tid]
          session.add(task)
          session.commit()
          print 'Adding Task: %s' % task.name
    session.close()
  
  def do_del(self, s):
    '''del [OPTIONS]
     -e (--entry) [ID]    Deletes the specified entry from the local db.
     -d (--date) [DATE]   Deletes all entries for the specified day from the
                          local db.
    '''
    session = self.smaker()
    delete  = None
    # First thing we need to see if there are any optional arguments in the
    # line and parse those first.  If there are any we will override the
    # default settings that have already been specified.
    opts, args  = getopt.getopt(s.split(), 'd:e:', ['date=','entry='])
    for opt, val in opts:
      if opt in ('-d', '--date'):
        delete = 'date'
        code, date = self._date(val)
        if not code: print date; return
      if opt in ('-e', '--entry'):
        delete  = 'entry'
        code, eid = self._int(val)
        if not code: print eid; return
    
    if delete == 'date':
      session.query(TimeEntry).filter(TimeEntry.date == date).delete()
      print 'Deleted all entries from %s' % date.strftime('%Y-%m-%d')
    if delete == 'entry':
      session.query(TimeEntry).filter(TimeEntry.id == eid).delete()
      print 'Deleted entry %s' % eid
    session.commit()
    session.close()
  
  def do_run(self, s):
    '''run [OPTIONS] [template_name] [time]
    The run function wil run a template with the options that were specified.
    
     -d (--date) [DATE]         Overrides the current date with the provided one.
     -f (--field) [NAME:VALUE]  Will add the name/value pair to the fields to
                                be replace dictionary.
    '''
    session = self.smaker()
    date    = datetime.date.today()
    fields  = {}
    # First thing we need to see if there are any optional arguments in the
    # line and parse those first.  If there are any we will override the
    # default settings that have already been specified.
    opts, args  = getopt.getopt(s.split(), 'd:f:', ['date=','field='])
    for opt, val in opts:
      if opt in ('-d', '--date'):
        try:
          year, month, day = val.split('-')
          date    = datetime.date(int(year), int(month), int(day))
        except:
          print 'Invalid Year Argument.  Must be YYYY-MM-DD'
          return
      if opt in ('-f', '--field'):
        try:
          dset = val.split(':')
          fields[dset[0].upper()] = dset[1]
        except:
          print 'Invalid Field Parameter.  Must be name:value'
    if args < 2:
      print 'Not enough Arguments.'
      return
    try:
      hour, minute  = args[1].split(':')
      start_time    = datetime.datetime(date.year, date.month, date.day, 
                                        int(hour), int(minute))
    except:
      print 'Invalid Parameters, cannot run template.'
      return
    try:
      template  = session.query(Template).filter_by(name=args[0]).one()
    except:
      print 'Not a valid Template ID.'
      return
    tracker = start_time
    for action in template.actions:
      entry   = action.gen_entry(tracker, fields)
      tracker = tracker + datetime.timedelta(minutes=action.duration)
      session.add(entry)
    session.commit()
    
  def do_tmpl_new(self, s):
    '''tmpl_new
    Asks the user for the values needed to create a new template.  The name
    must not contain spaces, however there is no restriction on the 
    description field.
    '''
    tmpl = Template()
    tmpl.name         = raw_input('Enter Name : ')
    tmpl.description  = raw_input('Enter Description : ')
    session = self.smaker()
    session.add(tmpl)
    session.commit()
    session.close() 
  
  def do_tmpl_add(self, s):
    '''tmpl_add [OPTIONS] [template_name] [stack_id] [duration] 
                  [department_id] [project_id] [task_id] [description]
    
    Creates a new action for the specified template.  Also note that in the
    description and notes fields, if the user uses {field_name}, then that can
    be replaced when running the template by specifying -f field_name:value.
    
     -b (--billable)        Sets the billable flag to true.
    '''
    session         = self.smaker()
    action          = Action()
    action.billable = False
    # First thing we need to see if there are any optional arguments in the
    # line and parse those first.  If there are any we will override the
    # default settings that have already been specified.
    opts, args  = getopt.getopt(s.split(), 'd:l', ['date=','long'])
    
    for opt, val in opts:
      if opt in ('-b', '--billable'):
        action.billable = True
    
    try:
      template  = session.query(Template).filter_by(name=args[0]).one()
    except:
      print 'Could not find a template by that name.'
      return
    
    if len(args) >= 6:
      try:
        action.template_id    = template.id
        action.stack          = int(args[1])
        action.duration       = int(args[2])
        action.department_id  = int(args[3])
        action.project_id     = int(args[4])
        action.task_id        = int(args[5])
      except:
        print 'Invalid Input, Argument was not integer.'
        return
      if len(args) > 6:
        action.description    = ' '.join(args[6:])
      else:
        action.description    = raw_input('Enter Description : ')
      action.notes            = raw_input('      Enter Notes : ')
      
    try:
      session.add(action)
      session.commit()
    except:
      print 'Could not add action to database.'
      session.close()
    else:
      print 'Action added to Database.'
      session.close()
    
  
  def do_tmpl_show(self, s):
    '''tshow [NAME]
    Shows the current template and it's associated actions.
    '''
    session = self.smaker()
    try:
      tmpl  = session.query(Template).filter_by(name=s).one()
      self._print_template(tmpl)
    except:
      print 'Could not find any templates by that name.'
  
  def do_show(self, s):
    '''show [OPTIONS]
    Shows the entries associated with a given date.  If no date is given the
    current date will be used.
    '''
    date  = datetime.date.today()
    lform = False
    bill  = {True: 'X', False: ' '}
    
    # First thing we need to see if there are any optional arguments in the
    # line and parse those first.  If there are any we will override the
    # default settings that have already been specified.
    opts, args  = getopt.getopt(s.split(), 'd:l', ['date=','long'])
    for opt, val in opts:
      if opt in ('-d', '--date'):
        try:
          year, month, day = val.split('-')
          date    = datetime.date(int(year), int(month), int(day))
        except:
          print 'Invalid Year Argument.  Must be YYYY-MM-DD'
          return
      if opt in ('-l', '--long'):
        lform = True
    
    session = self.smaker()
    entries = session.query(TimeEntry).filter_by(date=date).order_by(TimeEntry.start_time).all()
    
    if lform:
      print '%-4s %1s %-10s %-5s %-5s %-30s %-30s %-40s %-30s\n' %\
            ('ID', 'B', 'DATE', 'START', 'END', 'DEPARTMENT', 'PROJECT', 'TASK', 'DESCRIPTION') +\
            '%-4s %s %-10s %-5s %-5s %-30s %-30s %-40s %-30s'   %\
            ('-'*4, '-', '-'*10, '-'*5, '-'*5, '-'*30, '-'*30, '-'*40, '-'*30)
    else:
      print '%-4s %s %-10s %-5s %-5s %-5s %-5s %-5s %-30s\n'  %\
            ('ID', 'B', 'DATE', 'START', 'END', 'DEPT', 'PROJ', 'TASK', 'DESCRIPTION') +\
            '%-4s %s %-10s %-5s %-5s %-5s %-5s %-5s %-30s'    %\
            ('-'*4, '-', '-'*10, '-'*5, '-'*5, '-'*5, '-'*5, '-'*5, '-'*30)
    for entry in entries:
      if lform:
        print '%-4d %s %-10s %-5s %-5s %-30s %-30s %-40s %-30s' %\
              (entry.id, bill[entry.billable], entry.date.strftime('%Y-%m-%d'),
               entry.start_time.strftime('%H:%M'), entry.end_time.strftime('%H:%M'),
               '%-25s[%3d]' % (entry.department.name[:25], entry.department.id), 
               '%-25s[%3d]' % (entry.project.name[:25], entry.project.id),
               '%-35s[%3d]' % (entry.task.name[:35], entry.task.id),
               entry.description)
      else:
        print '%-4s %s %-10s %-5s %-5s %-5s %-5s %-5s %-30s' %\
              (entry.id, bill[entry.billable], entry.date.strftime('%Y-%m-%d'),
               entry.start_time.strftime('%H:%M'), entry.end_time.strftime('%H:%M'),
               '[%3d]' % entry.department.id, '[%3d]' % entry.project.id,
               '[%3d]' % entry.task.id, entry.description)
    
  
  def do_quit(self, s):
    '''quit
    Quits Timecard.'''
    sys.exit()
  
if __name__ == '__main__':
  if len(sys.argv) > 1:
    TimeCardCLI().onecmd(' '.join(sys.argv[1:]))
  else:
    TimeCardCLI().cmdloop()