import keyring

# Clear stored credentials (optional)
keyring.delete_password("gmail", "address")
keyring.delete_password("gmail", "password")


# Imposta l'email e la password specifica per l'app
keyring.set_password("gmail", "daniel.pozzoli86@gmail.com", "okbz yzyc ljto jnvt")