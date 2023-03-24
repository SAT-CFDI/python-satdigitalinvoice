from satdigitalinvoice.microsoft_auth.auth_code_receiver import AuthCodeReceiver


def test_auth_receiver():
    server = AuthCodeReceiver(port=0)
    a = server.get_port()
    assert a < 65536
