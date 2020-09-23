import couchdb


couch_protocol = "http"
couch_user = "whisk_admin"
couch_password = "some_passw0rd"
couch_host = "192.168.196.65"
couch_port = "5984"

couch = couchdb.Server(
    "{}://{}:{}@{}:{}/".format(
        couch_protocol, couch_user, couch_password, couch_host, couch_port
    )
)

couch_activations = couch["whisk_distributed_activations"]
couch_whisks = couch["whisk_distributed_whisks"]

# for id in couch_users["_design/_auth"]:
#     print(id)

# doc_function = couch_whisks["guest/function0"]
# # print(doc_function)
# doc_function["limits"]["memory"] = 45
# couch_users.save(doc_function)

# activation_id = "fb886d9c540b43d2886d9c540b43d297"
activation_id = "de910bbc780f4ae3910bbc780f9ae311"
doc_activation = couch_activations.get("guest/{}".format(activation_id))
if doc_activation is not None:
    print(doc_activation["annotations"])
