#!/usr/bin/env python3

from datetime import datetime
import os
import logging

#--------------------------------------------------------------------------------------------------------------------------------------------------------

loggersrv = logging.getLogger('logsrv')
_column_names = ('clientMachineId', 'machineName', 'applicationId', 'skuId', 'licenseStatus', 'lastRequestTime', 'kmsEpid', 'requestCount', 'lastRequestIP')

# sqlite3 is optional.
available = False
try:
        import sqlite3
        available = True
except ImportError:
        pass

def sql_initialize(dbName):
        if available is False:
                loggersrv.info("'sqlite3' module not found! SQLite database support cannot be enabled.")
                return
        loggersrv.debug(f'SQLite database support enabled. Database file: "{dbName}"')
        if not os.path.isfile(dbName):
                # Initialize the database
                loggersrv.debug(f'Initializing database file "{dbName}"...')
                with sqlite3.connect(dbName) as con:
                        cur = con.cursor()
                        cur.execute("CREATE TABLE clients(clientMachineId TEXT, machineName TEXT, applicationId TEXT, skuId TEXT, licenseStatus TEXT, lastRequestTime INTEGER, kmsEpid TEXT, requestCount INTEGER, PRIMARY KEY(clientMachineId, applicationId, skuId))")

        if os.path.isfile(dbName):
                # Update database
                with sqlite3.connect(dbName) as con:
                        cur = con.cursor()
                        # Create simple "metadata" table if not exists.
                        cur.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);")
                        # Get the current schema version
                        cur.execute("SELECT value FROM metadata WHERE key='schema_version';")
                        row = cur.fetchone()
                        if row is None:
                                current_version = 0
                        else:
                                current_version = int(row[0])
                        loggersrv.debug(f'Current database schema version: {current_version}')
                        # Apply necessary migrations
                        if current_version < 1:
                                # v1: Add "lastRequestIP" column to "clients" table.
                                loggersrv.info("Upgrading database schema to version 1...")
                                cur.execute("ALTER TABLE clients ADD COLUMN lastRequestIP TEXT;")
                                cur.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', '1');")
                                loggersrv.info("Database schema updated to version 1.")
                        if current_version < 2:
                                # v2: Recreate "clients" table with new schema with updated PK to faciliate multiple SKUs per clientMachineId and applicationId.
                                loggersrv.info("Upgrading database schema to version 2...")
                                con.commit()
                                cur.execute("BEGIN IMMEDIATE")
                                cur.execute("ALTER TABLE clients RENAME TO clients_old;")
                                cur.execute("""
                                CREATE TABLE clients (
                                        clientMachineId TEXT,
                                        machineName TEXT,
                                        applicationId TEXT,
                                        skuId TEXT,
                                        licenseStatus TEXT,
                                        lastRequestTime INTEGER,
                                        kmsEpid TEXT,
                                        requestCount INTEGER,
                                        lastRequestIP TEXT,
                                        PRIMARY KEY(clientMachineId, applicationId, skuId)
                                )
                                """)

                                # Handle duplicates by keeping only the most recent entry for each (clientMachineId, applicationId, skuId) combination.
                                cur.execute("""
                                INSERT INTO clients
                                SELECT *
                                FROM clients_old AS c
                                WHERE rowid = (
                                        SELECT rowid
                                        FROM clients_old AS c2
                                        WHERE c2.clientMachineId IS c.clientMachineId
                                        AND c2.applicationId IS c.applicationId
                                        AND c2.skuId IS c.skuId
                                        ORDER BY c2.lastRequestTime DESC, c2.rowid DESC
                                        LIMIT 1
                                )
                                """)

                                cur.execute("DROP TABLE clients_old")

                                cur.execute("""
                                INSERT OR REPLACE INTO metadata (key, value)
                                VALUES ('schema_version', '2')
                                """)

                                loggersrv.info("Database schema updated to version 2.")

def sql_get_all(dbName):
        if available is False:
                return
        if not os.path.isfile(dbName):
                return None
        with sqlite3.connect(dbName) as con:
                con.row_factory = sqlite3.Row
                cur = con.cursor()
                cur.execute(f"SELECT {', '.join(_column_names)} FROM clients")
                clients = []
                for row in cur.fetchall():
                        loggersrv.debug(f"Row: {row}")
                        obj = {}
                        for col_name in _column_names:
                                if col_name == "lastRequestTime":
                                        obj[col_name] = datetime.fromtimestamp(row['lastRequestTime']).isoformat()
                                else:
                                        obj[col_name] = row[col_name]
                        loggersrv.debug(f"Obj: {obj}")
                        clients.append(obj)
                return clients

def sql_update(dbName, infoDict):
        if available is False:
                return

        # make sure all column names are present
        for col_name in _column_names:
                if col_name in ["requestCount", "kmsEpid"]:
                        continue
                if col_name not in infoDict:
                        raise ValueError(f"infoDict is missing required column: {col_name}")

        with sqlite3.connect(dbName) as con:
                con.row_factory = sqlite3.Row
                cur = con.cursor()
                cur.execute(f"SELECT {', '.join(_column_names)} FROM clients WHERE clientMachineId=:clientMachineId AND applicationId=:applicationId AND skuId=:skuId;", infoDict)
                data = cur.fetchone()
                if not data:
                        # Insert new row with all given info
                        infoDict["kmsEpid"] = ""  # Default empty value
                        infoDict["requestCount"] = 1
                        cur.execute(f"""INSERT INTO clients ({', '.join(_column_names)})
                                VALUES ({', '.join(':' + col for col in _column_names)});""", infoDict)

                else:
                        # Update only changed columns
                        common_postfix = "WHERE clientMachineId=:clientMachineId AND applicationId=:applicationId AND skuId=:skuId"
                        def update_column_if_changed(column_name, new_value):
                                assert "clientMachineId" in infoDict and "applicationId" in infoDict, "infoDict must contain 'clientMachineId' and 'applicationId'"
                                if column_name not in _column_names:
                                        raise ValueError(f"Unknown column name: {column_name}")
                                if data[column_name] != new_value:
                                        query = f"UPDATE clients SET {column_name}=:value {common_postfix}"
                                        cur.execute(query, {"value": new_value, "clientMachineId": infoDict['clientMachineId'], "applicationId": infoDict['applicationId'], "skuId": infoDict['skuId']})

                        # Dynamically check and maybe update all columns
                        for column_name in _column_names:
                                if column_name in ["clientMachineId", "applicationId", "skuId", "requestCount"]:
                                        continue  # Skip these columns
                                if column_name == "kmsEpid":
                                        # this one can only be updated by the special function
                                        continue
                                update_column_if_changed(column_name, infoDict[column_name])

                        # Finally increment requestCount
                        cur.execute(f"UPDATE clients SET requestCount=requestCount+1 {common_postfix}", infoDict)

def sql_update_epid(dbName, kmsRequest, response, appName, skuName):
        if available is False:
                return

        cmid = str(kmsRequest['clientMachineId'].get())
        with sqlite3.connect(dbName) as con:
                cur = con.cursor()
                cur.execute("UPDATE clients SET kmsEpid=? WHERE clientMachineId=? AND applicationId=? AND skuId=?;",
                        (str(response["kmsEpid"].decode('utf-16le')), cmid, appName, skuName))
