import sqlite3 

# connecct to (or create) a local SQLite DB File
connection = sqlite3.connect("student.db")

# create a cursor
cursor = connection.cursor()

# Define a SQL statement to create a table (if not exists)

table_info = """

CREATE TABLE IF NOT EXISTS student(
    name VARCHAR(25),
    class VARCHAR(25),
    section VARCHAR(25),
    marks INTEGER);

"""

cursor.execute(table_info)

# insert some sample records
cursor.execute("INSERT INTO student VALUES ('Malik','DataScience','A','70')")
cursor.execute("INSERT INTO student VALUES ('Ali','Development','B','90')")
cursor.execute("INSERT INTO student VALUES ('Khalid','Maths','A','10')")
cursor.execute("INSERT INTO student VALUES ('Maham','DataScience','B','20')")
cursor.execute("INSERT INTO student VALUES ('Kanza','Development','A','60')")
cursor.execute("INSERT INTO student VALUES ('Qasim','DataScience','C','99')")
cursor.execute("INSERT INTO student VALUES ('Haider','Development','A','40')")
cursor.execute("INSERT INTO student VALUES ('John','Maths','D','20')")
cursor.execute("INSERT INTO student VALUES ('Harris','Development','A','33')")
cursor.execute("INSERT INTO student VALUES ('Aalina','Maths','C','66')")
cursor.execute("INSERT INTO student VALUES ('Jacob','Development','B','100')")


# print out inserted records to confirm
print("The Inserted records are : ")

data = cursor.execute("Select * from student")

for row in data:
    print(row)

# this we are writing to implement changes
connection.commit()

# close the connection
connection.close()
