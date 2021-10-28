<?php
# Change variables for youself!
$sqlite_path = "/opt/share/py-kms";

#######################
# ---- START SCRIPT----
#######################
$dbn = "sqlite:$sqlite_path/clients.db";

try {
$dbh = new PDO($dbn);
} catch (PDOException $e) {
echo $e->getMessage();
}

$sql = "SELECT sum(requestCount) FROM clients";
foreach ($dbh->query($sql) as $row) {
	$requestCount = $row[0];
}

$sql = "SELECT clientMachineId, machineName, applicationId, skuId, licenseStatus, lastRequestTime, kmsEpid, requestCount FROM clients";

echo "<table border=1 cellspacing=0 cellpadding=2 width=95% align=center>";
echo "<thead bgcolor=silver>";
echo "<tr>";
echo "<th>Machine name</th>";
echo "<th>App ID</th>";
echo "<th>App version</th>";
echo "<th>License status</th>";
echo "<th>Last request time</th>";
echo "<th>Request count</th>";
echo "</tr>";
echo "<thead>";
foreach ($dbh->query($sql) as $row) {
    echo "<tr>";
	  //echo "<td>" . $row['clientMachineId'] . "</td>";
      echo "<td>" . $row['machineName'] . "</td>";
	  echo "<td>" . $row['applicationId'] . "</td>";
      echo "<td>" . $row['skuId'] . "</td>";
	  echo "<td>" . $row['licenseStatus'] . "</td>";
      echo "<td>" . date("d.m.Y H:i:s",$row['lastRequestTime']) . "</td>";
	  //echo "<td>" . $row['kmsEpid'] . "</td>";
      echo "<td>" . $row['requestCount'] . "</td>";
	echo "</tr>";
}
	echo "<tr bgcolor=silver>";
	  echo "<td colspan=5><b>Total request count:</b></td>";
	  echo "<td>" . $requestCount . "</td>";
	echo "</tr>";
echo "</table>";

$dbh = NULL;
?>
