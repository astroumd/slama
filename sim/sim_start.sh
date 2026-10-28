
if [ -d /global/rrao/sma_obs_perl ]; then
  # on-site
  export SMAOP=/global/rrao/sma_obs_perl
  export PATH=$SMAOP:$PATH
else
  # off-site, make sure you source this file from the slama/sim directory
  if [[ -n "$SMAGIT" ]]; then
      export PATH=$SMAGIT/../sim/bin:.:$PATH
  else
      echo "SMAGIT does not exist, simulator unlikely loaded"
  fi

fi
