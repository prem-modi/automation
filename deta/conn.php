<?php

// AWS EC2 MySQL DB Server
$servername = "3.69.166.243";
$username = "dns0108prd";
$password = "VMS>*yUkhbo0Ot0-->";
$dbname = "dns_app_prod";

$conn = new mysqli($servername, $username, $password, $dbname);
// Check connection
if ($conn->connect_error) {
    die("Connection failed: " . $conn->connect_error);
}

?>
