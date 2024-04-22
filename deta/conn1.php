<?php

$root = $_SERVER['DOCUMENT_ROOT'];
$envFilepath = "$root/.env";
$env = parse_ini_file($envFilepath);

$servername = $env['servername'];
$username = $env['username'];
$password = '4563233ssssssssssss';
$dbname = $env['dbname'];

$conn = new mysqli($servername, $username, $password, $dbname);
// Check connection
if ($conn->connect_error) {
    die("Connection failed: " . $conn->connect_error);
}

?>
