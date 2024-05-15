<?php
// Command to be executed in Command Prompt
$command = 'ngrok http 8090';

// Execute the command in Command Prompt
$command_two = 'start cmd php demo68.php';

exec("start cmd /k \"{$command}\" 2>&1"."&& "."start cmd /k php demo68.php 2>&1");

echo "Output: \n";
foreach ($output as $line) {
    echo $line . "\n";
}

// Print the return code
echo "Return code: $returnCode\n";
?>
