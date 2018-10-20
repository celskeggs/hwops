# -*- coding: utf-8 -*-
import cgitb; cgitb.enable()
import db
import os
import jinja2
import kerbparse
import moira
import urlparse

jenv = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"), autoescape=True)

class Cell:
    def __init__(self, name, rack, slot, id=None, span=1):
        self.names = [name]
        self.ids = [id] if id is not None else None
        self.span = span
        self.rack = rack
        self.slot = slot

    def merge(self, extra_name, extra_id):
        assert self.ids is not None
        self.names += [extra_name]
        self.ids += [extra_id]

def spannify(columns, height):
    if not columns: return []
    new_rows = [[] for i in range(height)]
    for ci, column in enumerate(columns):
        ri = 0
        for cell in column:
            new_rows[ri].append(cell)
            if cell is not None:
                ri += cell.span
            else:
                ri += 1
    return new_rows

def generate_rack_table():
    racks = db.get_all_racks()
    racks.sort(key=lambda rack: rack.order)
    names_to_position = {rack.name: i for i, rack in enumerate(racks)}
    max_height = max(rack.height for rack in racks)
    devices_in_rack = [[] for rack in racks]
    for device in db.get_all_devices():
        devices_in_rack[names_to_position[device.rack]].append(device)
    racks_out = []
    columns = []
    for rack, devices in zip(racks, devices_in_rack):
        column = []
        next_slot = 1
        devices.sort(key=lambda device: device.rack_first_slot)
        for device in devices:
            if device.rack_first_slot < 1 or device.rack_last_slot < device.rack_first_slot or device.rack_last_slot > rack.height:
                raise Exception("device range error")
            if next_slot > device.rack_first_slot:
                backwards = next_slot - 1
                cidx = len(column) - 1
                while backwards >= device.rack_first_slot:
                    # TODO: handle this better (edge cases exist involving partial overlaps)
                    column[cidx].merge(device.name, device.id)
                    cidx -= 1
                    backwards -= column[cidx].span
            while next_slot < device.rack_first_slot:
                column.append(Cell("-- empty --", rack.name, next_slot))
                next_slot += 1
            slots = device.rack_last_slot - next_slot + 1
            if slots > 0:
                column.append(Cell(device.name, rack.name, next_slot, device.id, slots))
                next_slot += slots
        while next_slot <= rack.height:
            column.append(Cell("-- empty --", rack.name, next_slot))
            next_slot += 1
        while next_slot <= max_height:
            column.append(None)
            next_slot += 1
        columns.append(column[::-1])
        racks_out.append(rack)
    return racks_out, spannify(columns, max_height)

def is_hwop(user):
    return moira.has_access(user, "sipb-hwops@mit.edu")

def can_edit(user, device):
    if not user:
        return False
    if is_hwop(user):
        return True
    if device is not None and moira.has_access(user, device.owner):
        return True
    return False

def get_auth():
    user = kerbparse.get_kerberos()
    if user:
        link = ("https://" + os.environ["HTTP_HOST"].split(":")[0] + os.environ["REQUEST_URI"])
    else:
        link = ("https://" + os.environ["HTTP_HOST"].split(":")[0] + ":444" + os.environ["REQUEST_URI"])
    return user, link

def print_racks():
    racks, rows = generate_rack_table()
    user, authlink = get_auth()
    can_update = is_hwop(user)
    print("Content-type: text/html\n")
    print(jenv.get_template("racks.html").render(racks=racks, rows=rows, user=user, authlink=authlink, can_update=can_update).encode("utf-8"))

def print_rack(rack_name):
    user, authlink = get_auth()
    can_update = is_hwop(user)
    rack = db.get_rack(rack_name)
    print("Content-type: text/html\n")
    print(jenv.get_template("rack.html").render(rack=rack, user=user, authlink=authlink, can_update=can_update).encode("utf-8"))

def print_device(device_id):
    user, authlink = get_auth()
    device = db.get_device(device_id)
    can_update = can_edit(user, device)
    rack = db.get_rack(device.rack)
    stella = moira.stella(device.name)
    print("Content-type: text/html\n")
    print(jenv.get_template("device.html").render(device=device, rack=rack, user=user, authlink=authlink, can_update=can_update, stella=stella).encode("utf-8"))

def print_add(rack_name, slot):
    user, authlink = get_auth()
    can_update = is_hwop(user)
    rack = db.get_rack(rack_name)
    email = moira.user_to_email(user)
    assert 1 <= slot <= rack.height
    print("Content-type: text/html\n")
    print(jenv.get_template("add.html").render(rack=rack, user=user, email=email, slot=slot, authlink=authlink, can_update=can_update).encode("utf-8"))

# TODO: figure out better error handling for everything
def perform_add(params):
    user = kerbparse.get_kerberos()
    if not is_hwop(user):
        raise Exception("no access")
    rack = db.get_rack(params["rack"])
    first, last = int(params["first"]), int(params["last"])
    assert 1 <= first <= last <= rack.height
    if not moira.is_email_valid_for_owner(params["owner"]):
        raise Exception("bad owner")
    dev = db.Devices(name=params["devicename"], rack=params["rack"], rack_first_slot=first, rack_last_slot=last, ip=params.get("ip"), contact=params["contact"], owner=params["owner"], service_level=params["service"], model=params["model"], comments=params.get("comments"), last_updated_by=user)
    db.add(dev)
    print("Content-type: text/html\n")
    print(jenv.get_template("done.html").render(id=dev.id).encode("utf-8"))

def perform_update(params):
    user = kerbparse.get_kerberos()
    device = db.get_device(params["id"])
    if not can_edit(user, device):
        raise Exception("no access")
    rack = db.get_rack(params["rack"])
    first, last = int(params["first"]), int(params["last"])
    assert 1 <= first <= last <= rack.height
    if not moira.is_email_valid_for_owner(params["owner"]):
        raise Exception("bad owner")
    device.name = params["devicename"]
    device.rack = params["rack"]
    device.rack_first_slot = first
    device.rack_last_slot = last
    device.ip = params.get("ip")
    device.contact = params["contact"]
    device.owner = params["owner"]
    device.service_level = params["service"]
    device.model = params["model"]
    device.comments = params.get("comments")
    device.last_updated_by = user
    db.session.commit()
    print("Content-type: text/html\n")
    print(jenv.get_template("done.html").render(id=device.id).encode("utf-8"))