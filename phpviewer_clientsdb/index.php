<!DOCTYPE html>

<html lang=ru>
<head>
<meta charset=utf-8>
<title>py-kms server</title>
<meta name=description content="py-kms server">
<meta name=keywords content=php py-kms>
<body>

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
?>
<table border=1 cellspacing=0 cellpadding=2 width=95% align=center>
	<thead bgcolor=silver>
	<tr>
		<th>Machine name</th><th>App ID</th><th>App version</th><th>License status</th><th>Last request time</th><th>Request count</th>
	</tr>
	<thead>
<?php
foreach ($dbh->query($sql) as $row) {
	echo "	<tr>
		<td>" . $row['machineName'] . "</td>
		<td>" . $row['applicationId'] . "</td>
		<td>" . $row['skuId'] . "</td>
		<td>" . $row['licenseStatus'] . "</td>
		<td>" . date('d.m.Y H:i:s',$row['lastRequestTime']). "</td>
		<td>" .$row['requestCount'] . "</td>
	</tr>\n";
}
?>
	<tr bgcolor=silver>
		<td colspan=5><b>Total request count:</b></td>
<?php		
		echo "	<td>$requestCount</td>\n";
?>
	</tr>
</table>
<?php
$dbh = NULL;
?>

</body>
</html>
