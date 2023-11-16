def get_invoices_data(all_invoices, dp, rfc):
    for c in all_invoices.values():
        if c["Fecha"] == dp and c["Emisor"]["Rfc"] == rfc and c["TipoDeComprobante"] == "I":
            # print(c)
            print("- Rfc:", c["Receptor"]["Rfc"])
            print("  UsoCFDI:", c["Receptor"]["UsoCFDI"].code)
            print("  MetodoPago:", c["MetodoPago"].code)
            print("  Conceptos:")
            print("  - CuentaPredial:", repr(c["Conceptos"][0]["CuentaPredial"]))
            print("    ClaveProdServ:", repr(c["Conceptos"][0]["ClaveProdServ"].code))
            print("    Cantidad:", "1.0")
            print("    ClaveUnidad:", c["Conceptos"][0]["ClaveUnidad"].code)
            print("    Descripcion:", repr(c["Conceptos"][0]["Descripcion"].replace("MES DE SEPTIEMBRE DEL 2022", "{periodo}")))
            print("    ValorUnitario:", c["Conceptos"][0]["ValorUnitario"])
            print("  Total:", c["Total"])
            print()
