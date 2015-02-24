#!/usr/bin/python

# Imports

import sys, os, time, datetime, warnings, logging
from sunlight import openstates
import pyodbc, win32com, win32com.client
from attrconfig import AttrConfig

import urllib.request, urllib.error, urllib.parse
import re
#from pdb import set_trace

#Necessary Constants
parent_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
    # Log
FORMAT = "%(asctime)s %(message)s"
logfile = 'C:\Shannon\Programs\log.log'
logging.basicConfig(filename=logfile,level=logging.DEBUG, format=FORMAT)
ROW_TEMPLATE = {'watched': None, 'dateadd': datetime.datetime.now(), 'update_insert_flag':'insert'}
    # Program Constants
config = AttrConfig(os.path.join(parent_dir, 'config'))
dbconn = pyodbc.connect(config.default.dbconnstr)

class PowerBill:
    def __init__(self):
        print("Starting")
        #Order of Operations
        for st in config.default.states.split():
            logging.debug(str('%s Bills From OpenStates '%st.upper()))
            session = self.gatherBillDetails(st)
            if session:
                self.dbint = DBIntercept(st, session)
                self.watch(st, session)

            else: logging.debug(str('%s Has No New Bills'%(st)+ time.strftime("%B %d, %Y", time.gmtime())))

    def gatherBillDetails(self, st):
        pv_dt = (datetime.datetime.today() - datetime.timedelta(int(config.default.prev_days)))
        logging.debug(str('Gathering Bills from %s forward: '%pv_dt.isoformat() + time.strftime("%B %d, %Y", time.gmtime())))
        session = max([x for x in openstates.state_metadata(st)['session_details']])
        bill_list = [x for x in openstates.bills(state=st, subjects='tax') if (x['updated_at'][:4]==str(datetime.date.today().year))]
        bill_list2 = [x for x in openstates.bills(state=st, q='tax') if (x['updated_at'][:4]==str(datetime.date.today().year)) and (x not in bill_list)]
        bill_list.extend(bill_list2)

        bills = [openstates.bill_detail(st, bill['session'], bill['bill_id']) for bill in bill_list]

        self.bill_lines = []
        for bill in bills:
            if datetime.datetime.strptime(bill['updated_at'], '%Y-%m-%d %H:%M:%S') > pv_dt:
                    insertrow = {
                    'ost_id' : bill['id'],
                    'div' : bill['bill_id'][:1],
                    'st' : bill['state'],
                    'session' : bill['session'],
                    'num' : bill['bill_id'].split()[1],
                    'details' : bill['title'],
                    'title': bill['title'],
                    'year': time.strftime('%Y'),
                    'webpage' : ", ".join([x['url'] for x in bill['sources']])[:149],
                    'subjects' : ", ".join(bill['subjects'])[:249],
                    'dateadd': datetime.datetime.now(),
                    'email': True,
                    'watched' : 'New'
                    }
                    self.bill_lines.append(insertrow)
            else: continue

        if len(self.bill_lines)<1: return False
        else: return session

    def watch(self, state, session):
        rs_bills = re.compile('''BillID=(S|H)([0-9]+)''')
        if state == "NC":
            gs_bills = []
            for gs_num in config.NC.gs_nums.split():
                for line in urllib.request.urlopen(config.NC.goodsearchpage%(session, gs_num)).read().splitlines():
                    if rs_bills.search(str(line)):  gs_bills.append("".join(rs_bills.search(str(line)).groups()))
            gs_bills=set(gs_bills)

        for bill in self.bill_lines:
            if (state == "NC") and ("%s%s"%(bill['div'], bill['num']) in gs_bills): self.bill_lines[self.bill_lines.index(bill)]['watched'] = 'Yes'

        self.dbint.commit(self.bill_lines)
        #logging.debug(str('%s Bills '%(state)+ time.strftime("%B %d, %Y", time.gmtime())))

class DBIntercept:
    def __init__(self, state, session):
        # State as in the region - necessary for some DB lookups
        self.state = state
        self.watched_table = []
        self.session = session

    def type_warn(self, loc):
        logging.warning('Row %(row_num)i, Column %(col_num)i: not type %(col_type)s: Data %(col_data)s' %loc)

    def convert(self, table):
        logging.debug('Converting downloaded index to database types')

        # Convert types for database use
        for row_num, x_row in enumerate(table):
            # Give all rows a template
            table[row_num] = row = {}
            row.update(ROW_TEMPLATE)
            row.update(x_row)

            for col_num, col_name in enumerate(row):
                if not hasattr(config.legislation_table_types, col_name): continue
                col_type = getattr(config.legislation_table_types, col_name)
                col_data = row[col_name]

                if col_type == 'int':
                    # Intended to be an int
                    if col_data.isdigit():
                        # It is an int
                        col_data = int(col_data)
                    else:
                        # It's not an int
                        self.type_warn(locals())
                        col_data = 0

                row[col_name] = col_data

        # Rename columns
        # Assume no conflicts
        for row in table:
            for column_name in list(row.keys()):
                # Only rename columns they specify
                if not hasattr(config.LEGISLATION_TABLE, column_name): continue

                # Switch them in place
                new_column_name = getattr(config.LEGISLATION_TABLE, column_name)
                assert new_column_name not in list(row.keys())
                row[new_column_name] = row[column_name]
                del row[column_name]

    def convert_column_names(self, names):
        for num, name in enumerate(names):
            if hasattr(config.LEGISLATION_TABLE, name):
                names[num] = getattr(config.LEGISLATION_TABLE, name)
        return names

    def compare(self, table):
        logging.debug('Comparing the downloaded index to the one existing in the database')
        existing_table = dbconn.execute(config.billcommon.select_sql, [self.session, self.state]).fetchall()
        extab_cols = self.convert_column_names(config.billcommon.select_cols.split())
        comp_cols = self.convert_column_names(config.billcommon.compare_cols.split())

        # For each row we have indexed
        for row1_num, row1 in enumerate(table):
            # For each row indexed before
            for row2_num, row2 in enumerate(existing_table):
                # Convert row2 (the old indices) to a dictionary using conf cols as keys
                row2 = dict(list(zip(extab_cols, row2)))
                # Match to the new index entry
                if all([str(row1[x]) == str(row2[x]) for x in comp_cols]):
                    # Update the old entry with new info
                    row2.update(row1)
                    table[row1_num] = row2
                    table[row1_num]['update_insert_flag'] = 'update'
                    self.watched_table.append(existing_table[row2_num][4])

    def get_query_table(self, table, flag, printed=False):
        logging.debug('Formulating data for query: %s' %flag)

        # Update these bills in the DB with this info
        if printed:
            # For greenlist
            cols = self.convert_column_names(['div', 'num', 'details', 'webpage'])
        else:
            # for a query
            cols = self.convert_column_names(getattr(config.billcommon, '%s_cols' %flag).split())

        data = []
        for row in table:
            # Only include the rows for this kind of update
            if row['update_insert_flag'] != flag: continue
            data.append([])
            for col_name in cols:
                data[-1].append(row[col_name])
        return data

    def query(self, table, flag):
        # Query the database - either update or insert
        sql = getattr(config.billcommon, '%s_sql' %flag)
        data = self.get_query_table(table, flag)
        if not data:
            logging.warning('%s query interrupted. No input rows.' %flag)
            return
        logging.debug('Executing SQL: %s' %sql)
        if data:
            try:
                cursor = dbconn.cursor()
                cursor.executemany(sql, data)
                cursor.close()
                dbconn.commit()
            except:
                logging.exception('SQL execution failed.')

    def generate_printout(self, table):
        logging.debug('Exporting list of new bills to file.')
        txt=''
        try:
            path = getattr(config, self.state).output
            logging.debug('Opening output bill file for writing, %s' %path)
            greenfile = open(path, 'w')

        except:
            logging.exception('Unable to open output bill file for writing. Do you have permission?')
            return

        for type_flag, refnum, details, webpage in self.get_query_table(table, 'insert', printed=True):
            if len([ln['email'] for ln in table if ln['lt_BillNum']==refnum and ln['email']==False])>0:
                print("Not Tax: ",refnum)
                continue
            txt = str(txt+"\n"+('%(type_flag)s.%(refnum)s -- %(details)s\n%(webpage)s\n' %locals()))
            greenfile.write('%(type_flag)s.%(refnum)s -- %(details)s\n%(webpage)s\n' %locals())

        if self.watched_table:
            greenfile.write('\nWatched Bills\n')
            txt = str(txt+"\nWatched Bills\n")
            watched_details = dbconn.execute(config.watched.select_sql, [self.session, self.state, "Yes"]).fetchall()
            for row in watched_details:
                if row[1] in self.watched_table:
                    txt = str(txt+"\n"+'%s.%s -- %s , %s\n %s\n'%(str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4])))
                    greenfile.write('%s.%s -- %s , %s\n %s\n'%(str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4])))
        if len(txt)>25: return txt
        else: return False

    def send_mail(self, text):
        #print("sending mail")
        if not text: return
        else:
            subject=str(self.state.upper() + ' Legislation ' + time.strftime("%B %d, %Y", time.gmtime()))
            if self.state.upper() == 'NC':
                recipient = ''
            else:
                recipient = ''

            olMailItem = 0x0
            obj = win32com.client.Dispatch("Outlook.Application")
            newMail = obj.CreateItem(olMailItem)
            newMail.To = recipient
            newMail.Subject = subject
            newMail.BodyFormat= 1
            newMail.Body = str( subject + "\n\n" + text)
            newMail.Display()
            #newMail.Send()
        print("Done")

    def commit(self, table, print_needed=True):
        logging.debug('Committing changed or inserted entries to the database.')
        self.convert(table)
        self.compare(table)
        self.query(table, 'update')
        self.query(table, 'insert')
        txt = self.generate_printout(table)
        if print_needed: self.send_mail(txt)
        logging.debug('Changes committed.\n')


if __name__ == '__main__':
    PowerBill()
