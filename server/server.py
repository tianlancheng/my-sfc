# -*- coding: utf-8 -*-
from flask import Flask
from flask import request, session
from flask import jsonify
import json,os
import myconfig
from flask_pymongo import PyMongo
from flask_cors import CORS
from flask_socketio import SocketIO, emit,send,join_room, leave_room
from threading import Lock
import datetime
from bson.objectid import ObjectId
from kubernetes import client, config
import uuid,logging,time

app = Flask(__name__)
logger = logging.getLogger('server')

app.config.from_object(myconfig)
mongo = PyMongo(app)

CORS(app)
socketio = SocketIO(app, async_mode=app.config['ASYNC_MODE'])


# config.load_incluster_config()
config.load_kube_config()
v1=client.CoreV1Api()
beta1=client.ExtensionsV1beta1Api()


def background_thread():
    socketio.send('dd',broadcast=True)

@app.route('/api/user/login',methods=['POST'])
def login():
    data = json.loads(request.get_data().decode('utf-8'));
    user_set = mongo.db.user_set
    user = user_set.find_one({'username':data.get('username'),'password':data.get('password')})
    if user:
      user['id'] = str(user['_id'])
      user.pop('_id')
      return jsonify(status=200, msg='success', data=[user]), 200
    else:
      return jsonify(status=400, msg='error', data=None), 200

@app.route('/api/user/getUser',methods=['GET'])
def getUser():
    # id = request.args.get('id');
    user_set = mongo.db.user_set
    # user = user_set.find_one({'_id':ObjectId(id)})
    user = user_set.find_one({'username':'admin'})
    if user:
      return jsonify(status=200, msg='success', data=[user]), 200
    else:
      return jsonify(status=400, msg='error', data=None), 200

@app.route('/api/user',methods=['POST'])
def addUser():
    data = json.loads(request.get_data().decode('utf-8'));
    user_set = mongo.db.user_set
    user = user_set.find_one({'username':data['username']})
    if user:
      return jsonify(status=400, msg='username exist', data=None), 200
    data['_id'] = str(uuid.uuid1()).replace('-', '')[:12]
    data['id'] = data['_id']
    user_set.insert(data)
    return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/users',methods=['GET'])
def getUsers():
    users = list(mongo.db.user_set.find())
    return jsonify(status=200, msg='success', data=users), 200

#SF
@app.route('/api/SF',methods=['POST'])
def add_sf():
  data = json.loads(request.get_data().decode('utf-8'));
  data['type'] = 'Pod'
  if not data.get('pic'):
    data['pic']='/assets/static/pic/py_VR.png'
  sf_set = mongo.db.sf_set
  if sf_set.find_one({'_id':data['_id']}):
    return jsonify(status=400, msg='sf already exist', data=None), 200
  sf_set.insert(data)
  return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/addInstance',methods=['POST'])
def add_instance():
  data = json.loads(request.get_data().decode('utf-8'));
  if not mongo.db.sf_set.find_one({'_id':data['_id']}):
    return jsonify(status=400, msg='no this sf', data=None), 200
  start_sf_pod(data)
  return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/scaleDown',methods=['POST'])
def scale_down():
  data = json.loads(request.get_data().decode('utf-8'))
  if not mongo.db.sf_set.find_one({'_id':data['_id']}):
    return jsonify(status=400, msg='no this sf', data=None), 200
  sf_instance_set = mongo.db.sf_instance_set
  minRemain = 1000000000
  instanceId = ''
  instances = sf_instance_set.find({'sfId': data['_id']})
  for instance in instances: 
    if 'qsize' in instance and instance.get('qsize') < minRemain:
      minRemain = instance['qsize']
      instanceId = instance['_id']
  if instanceId:
    # sf_instance_set.update({'_id': selectId},{'$set':{'stop': True}})
    sf_instance_set.remove({'_id': instanceId})
    try:
      v1.delete_namespaced_pod(name=data['_id']+'-'+instanceId, namespace="default", body=client.V1DeleteOptions())
    except:
      logger.error('delete pod error!')
  return jsonify(status=200, msg='success', data=None), 200

def start_sf_pod(data):
  instanceId = str(uuid.uuid1()).replace('-', '')[:12]
  record={
    '_id': instanceId,
    'sfId': data['_id'],
    'image': data['image'],
    'policy': data['policy'],
    'cpu': data['cpu'],
    'memory': data['memory'],
    'status': 'creating',
    'time': time.time(),
    'stop': False,
    "ip": None,
    "receivedPackets": 0,
    "qsize": 0,
    "speed": 0
  }
  mongo.db.sf_instance_set.insert(record)

  next_hops={}
  sfs = list(mongo.db.sfc_set.find({'sfId':data['_id']}))
  for sf in sfs:
    if sf['next'] == None:
      instances = None
    else:
      instances = list(sf_instance_set.find({'sfId': sf['next'], 'status':'running'}))
    next_hops[sf['sfcId']] = instances

  args = {
    'server': app.config['SERVER'],
    'sfId': data['_id'],
    'instanceId': instanceId,
    'policy': data['policy'],
    'max_queue_size': app.config['MAX_QUEUE_SIZE'],
    'next_hops': next_hops
  }

  pod=client.V1Pod(api_version='v1',kind='Pod')
  pod.metadata=client.V1ObjectMeta(name=data['_id']+'-'+instanceId)

  # container1=client.V1Container(name="sff",image="sff:latest")
  # container1.args=[app.config['SERVER'], data['_id'], instanceId]
  # container1.image_pull_policy='IfNotPresent'
  # container2=client.V1Container(name='sf',image=data['image'])
  # container2.image_pull_policy='IfNotPresent'
  # containers = [container1,container2]
  resources=client.V1ResourceRequirements(limits={'cpu': data['cpu'],'memory': data['memory']},requests={'cpu': data['cpu'],'memory': data['memory']})
  container1=client.V1Container(name="sff",image=data['image'],resources=resources)
  container1.args=[json.dumps(args)]
  container1.image_pull_policy='IfNotPresent'
  containers = [container1]

  spec=client.V1PodSpec(containers=containers)
  pod.spec = spec
  v1.create_namespaced_pod(namespace="default",body=pod)

@app.route('/api/SF/<_id>',methods=['DELETE'])
def delete_sf(_id):
  sf_instance_set = mongo.db.sf_instance_set
  instances = sf_instance_set.find({'sfId': _id})
  for instance in instances:
    try:
      v1.delete_namespaced_pod(name=_id+'-'+instance['_id'], namespace="default", body=client.V1DeleteOptions())
    except:
      logger.error('delete pod error!')
  sf_instance_set.remove({'sfId':_id})
  mongo.db.sf_set.remove({'_id':_id})
  return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/SF',methods=['PUT'])
def update_sf():
  data = json.loads(request.get_data().decode('utf-8'));
  sf_set = mongo.db.sf_set
  if not sf_set.find_one({'_id':data['_id']}):
    return jsonify(status=400, msg='not find this sf', data=None), 200
  sf_set.update({"_id": data['_id']},{"$set":data})
  return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/SF/<_id>',methods=['GET'])
def get_sf(_id):
  sf_set = mongo.db.sf_set
  sf = sf_set.find_one({'_id': _id})
  instances = mongo.db.sf_instance_set.find({'sfId':sf['_id']})
  sf['instances'] = instances
  return jsonify(status=200, msg='success', data=sf), 200

@app.route('/api/SFs/all',methods=['GET'])
def get_sfs_all():
  sf_set = mongo.db.sf_set
  sfs = list(sf_set.find())
  sf_instance_set = mongo.db.sf_instance_set
  for sf in sfs:
    instances=list(sf_instance_set.find({'sfId':sf['_id']}))
    sf['instances'] = instances
    sf['num'] = len(instances)
  return jsonify(status=200, msg='success', data=sfs), 200

@app.route('/api/SFs',methods=['GET'])
def get_sfs():
  sf_set = mongo.db.sf_set
  sfs = list(sf_set.find({'type':'Pod'}))
  for sf in sfs:
    sf['id'] = sf['_id']
  return jsonify(status=200, msg='success', data=sfs), 200

@app.route('/api/removeSF',methods=['POST'])
def remove_sf():
  data = json.loads(request.get_data().decode('utf-8'))
  sfc_def = mongo.db.sfc_def_set.find_one({'_id':data['sfcId']})
  if not sfc_def:
    return jsonify(status=400, msg='not find sfc', data=None), 200
  order = data['order']-1
  if order<0 or order >= len(sfc_def['sfs']):
    return jsonify(status=400, msg='illegal order', data=None), 200
  
  if order-1 >= 0:
    last_sf = sfc_def['sfs'][order-1]['_id']
  else:
    last_sf = None
  if order+1 < len(sfc_def['sfs']):
    next_sf = sfc_def['sfs'][order+1]['_id']
  else:
    next_sf = None

  sfc_set = mongo.db.sfc_set
  if last_sf:
    sfc_set.update({'sfcId':data['sfcId'],'sfId':last_sf},{"$set":{'next':next_sf}})
  # sfc_set.remove({'sfcId':data['sfcId'], 'sfId':sfc_def['sfs'][order]})

  del sfc_def['sfs'][order]
  if not sfc_def['sfs']:
    mongo.db.sfc_set.remove({'sfcId':data['sfcId']})
    mongo.db.sfc_def_set.remove({'_id':data['sfcId']})
    return jsonify(status=200, msg='success', data=None), 200
  sfc_def['start_sf']=sfc_def['sfs'][0]['_id']
  mongo.db.sfc_def_set.update({'_id':data['sfcId']},sfc_def)
  return jsonify(status=200, msg='success',data=None), 200

@app.route('/api/insertSF',methods=['POST'])
def insert_sf():
  data = json.loads(request.get_data().decode('utf-8'));
  sfc_def = mongo.db.sfc_def_set.find_one({'_id':data['sfcId']})
  if not sfc_def:
    return jsonify(status=400, msg='not find sfc', data=None), 200

  sf = mongo.db.sf_set.find_one({'_id':data['sfId']})
  if not sf:
    return jsonify(status=400, msg='not find sf', data=None), 200

  for item in sfc_def['sfs']:
    if data['sfId'] == item['_id']:
      return jsonify(status=400, msg='The sfc already exist this sf', data=None), 200
  
  order=data.get('order')
  if not order or order<1:
    order=1
  elif order>len(sfc_def['sfs'])+1:
    order=len(sfc_def['sfs'])+1
  order = order -1
  sfc_def['sfs'].insert(order,sf)

  if order-1 >= 0:
    last_sf = sfc_def['sfs'][order-1]['_id']
  else:
    last_sf = None
  if order+1 < len(sfc_def['sfs']):
    next_sf = sfc_def['sfs'][order+1]['_id']
  else:
    next_sf = None

  sfc_set = mongo.db.sfc_set
  sfc_set.remove({'sfcId':data['sfcId'],'sfId':data['sfId']})
  sfc_set.insert({'_id':str(uuid.uuid1()).replace('-', '')[:12],'sfcId':data['sfcId'],'sfId':data['sfId'],'next':next_sf})
  time.sleep(5)
  if last_sf:
    sfc_set.update({'sfcId':data['sfcId'],'sfId':last_sf},{"$set":{'next':data['sfId']}})
  
  sfc_def['start_sf'] = sfc_def['sfs'][0]['_id']
  mongo.db.sfc_def_set.update({'_id':data['sfcId']},sfc_def)
  return jsonify(status=200, msg='success',data=None), 200

lock = Lock()
#SFC
@app.route('/api/SFC',methods=['POST'])
def add_sfc():
  data = json.loads(request.get_data().decode('utf-8'));
  with lock:
    sfc_set = mongo.db.sfc_set
    sfc_def_set = mongo.db.sfc_def_set
    if sfc_def_set.find_one({'name':data['name']}):
      return jsonify(status=400, msg='sfc already exist', data=None), 200
    SFs = data.get('SFs')
    if not SFs:
      return jsonify(status=400, msg='SFs can not be empty', data=None), 200
    maxItem = sfc_def_set.find().sort([('_id', -1)]).limit(1)
    sfcId=1
    for item in maxItem:
      sfcId = item['_id']+1
    sf_array = []
    records = []
    for i in range(0,len(SFs)):
      if i<len(SFs)-1:
        next = SFs[i+1]['_id']
      else:
        next = None
      record={
        '_id': str(uuid.uuid1()).replace('-', '')[:12],
        'sfcId': sfcId,
        'sfId': SFs[i]['_id'],
        'next': next
      }
      records.append(record)
      sf_array.append(SFs[i])
    sfc_def_set.insert({'_id':sfcId,'name':data['name'],'sfs':sf_array,'start_sf':sf_array[0]['_id']})
    sfc_set.insert_many(records)
  return jsonify(status=200, msg='success', data={'sfcId':sfcId}), 200

@app.route('/api/SFC/<sfcId>',methods=['DELETE'])
def delete_sfc(sfcId):
  mongo.db.sfc_set.remove({'sfcId':int(sfcId)})
  mongo.db.sfc_def_set.remove({'_id':int(sfcId)})
  return jsonify(status=200, msg='success', data=None), 200


@app.route('/api/SFC/<sfcId>',methods=['GET'])
def get_sfc(sfcId):
  sfcs = mongo.db.sfc_def_set.find_one({'_id':int(sfcId)})
  return jsonify(status=200, msg='success', data=sfcs), 200

@app.route('/api/SFCs',methods=['GET'])
def get_sfcs():
  sfcs = list(mongo.db.sfc_def_set.find())
  return jsonify(status=200, msg='success', data=sfcs), 200

@app.route('/api/acl',methods=['POST'])
def add_acl():
  data = json.loads(request.get_data().decode('utf-8'));
  acl_set = mongo.db.acl_set
  if acl_set.find_one({'rspId':data['rspId']}):
    return jsonify(status=400, msg='rspId already exist', data=None), 200
  data['_id'] = str(uuid.uuid1()).replace('-', '')
  data['action'] = 'create'
  acl_set.insert(data)
  return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/acl',methods=['DELETE'])
def delete_acl():
  data = json.loads(request.get_data().decode('utf-8'));
  acl_set = mongo.db.acl_set
  if not acl_set.find_one({'rspId':data['rspId']}):
    return jsonify(status=400, msg='rspId does not exist', data=None), 200
  acl_set.update({'respId': data['rspId']},{'$set':{'action': 'delete'}})
  return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/heartbeat',methods=['POST'])
def heartbeat():
  data = json.loads(request.get_data().decode('utf-8'));
  t = time.time()
  data['time'] = t
  data['status'] = 'running'
  sf_instance_set = mongo.db.sf_instance_set
  
  next_hops={}
  if data.get('instanceId') == 'dispatcher':
    data['cpu'] = '0.2'
    data['memory'] = '128Mi'
    data['image'] = 'dispatcher:latest'
    sf_instance_set.update({"_id": data['ip']},{"$set":data},upsert=True)
    sfcs = list(mongo.db.sfc_def_set.find())
    for sfc in sfcs:
      instances = list(sf_instance_set.find({'sfId': sfc['start_sf'], 'status':'running'}))
      next_hops[sfc['_id']] = instances
  else:
    sf_instance_set.update({"_id": data['instanceId']},{"$set":data})
    sfs = list(mongo.db.sfc_set.find({'sfId':data['sfId']}))
    for sf in sfs:
      if sf['next'] == None:
        instances = None
      else:
        instances = list(sf_instance_set.find({'sfId': sf['next'], 'status':'running'}))
      next_hops[sf['sfcId']] = instances
  # print(next_hops)
  return jsonify(status=200, msg='success', data=next_hops), 200

@socketio.on('connect', namespace='/socket/client')
def client_connect():
    logger.info('client connect:'+request.sid)

@socketio.on('disconnect', namespace='/socket/client')
def client_disconnect():
    logger.info('client disconnected:'+request.sid)


def start_dispatcher_pod(data):
  sfcs = list(mongo.db.sfc_def_set.find())
  next_hops={}
  for sfc in sfcs:
    instances = list(mongo.db.sf_instance_set.find({'sfId': sfc['start_sf'], 'status':'running'}))
    next_hops[sfc['_id']] = instances
  args = {
    'server': app.config['SERVER'],
    'sfId': data['_id'],
    'instanceId': 'dispatcher',
    'policy': data['policy'],
    'max_queue_size': app.config['MAX_QUEUE_SIZE'],
    'next_hops': next_hops
  }
  mongo.db.sf_instance_set.remove({'sfId':'dispatcher'})

  resources=client.V1ResourceRequirements(limits={'cpu': data['cpu'],'memory': data['memory']},requests={'cpu': data['cpu'],'memory': data['memory']})
  container1=client.V1Container(name="dispatcher",image=data['image'],resources=resources)
  container1.args=[json.dumps(args)]
  container1.image_pull_policy='IfNotPresent'
  container1.ports = [client.V1ContainerPort(container_port = 6000, host_port=6000, protocol='UDP')]
  containers = [container1]

  pod_spec=client.V1PodSpec(containers=containers)
  # pod.spec = pod_spec
  # v1.create_namespaced_pod(namespace="default",body=pod)
  template_metadata = client.V1ObjectMeta(labels={'type':'dispatcher'})
  template = client.V1PodTemplateSpec(metadata=template_metadata,spec = pod_spec)
  daemonset_spec = client.V1beta1DaemonSetSpec(template=template)
  daemonset = client.V1beta1DaemonSet(api_version='extensions/v1beta1',kind='DaemonSet',spec=daemonset_spec)
  daemonset.metadata=client.V1ObjectMeta(name='dispatcher',labels={'type':'dispatcher'})
  beta1.create_namespaced_daemon_set(namespace="default",body=daemonset)

  # mongo.db.sf_instance_set.insert(record)

if __name__ == '__main__':
    sf_set = mongo.db.sf_set
    data = {'_id':'dispatcher',
            'remark':'dispatcher',
            'image':'dispatcher:latest',
            'description': 'forward data',
            'autoscale':False,
            'type': 'DaemonSet',
            'cpu': '0.2',
            'memory': '128Mi',
            'policy': 'ResourceAware', #ResourceAware/RoundRobin
            'pic': '/assets/static/pic/f5.png'
            }
    sf_set.update({'_id':'dispatcher'},{"$set":data},upsert=True)

    ret = beta1.list_daemon_set_for_all_namespaces(watch=False,label_selector='type=dispatcher')
    if not ret.items:
      print('start dispatcher daemonSet')
      start_dispatcher_pod(data)
    app.run(host='0.0.0.0',port=5000,debug=False,threaded=True)
    # beta1.delete_namespaced_daemon_set(name='dispatcher',namespace="default",body=client.V1DeleteOptions())
    # socketio.run(app)
