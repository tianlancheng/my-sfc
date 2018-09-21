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
      return jsonify(status=400, msg='error', data=None), 400

@app.route('/api/user/getUser',methods=['GET'])
def getUser():
    id = request.args.get('id');
    user_set = mongo.db.user_set
    user = user_set.find_one({'_id':ObjectId(id)})
    if user:
      user['id'] = str(user['_id'])
      user.pop('_id')
      return jsonify(status=200, msg='success', data=[user]), 200
    else:
      return jsonify(status=400, msg='error', data=None), 400

#SF
@app.route('/api/SF',methods=['POST'])
def add_sf():
  data = json.loads(request.get_data().decode('utf-8'));
  sf_set = mongo.db.sf_set
  if sf_set.find_one({'_id':data['_id']}):
    return jsonify(status=400, msg='sf already exist', data=None), 400
  sf_set.insert(data)
  start_pod(data)
  return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/scaleUp',methods=['POST'])
def scale_up():
  data = json.loads(request.get_data().decode('utf-8'));
  if not mongo.db.sf_set.find_one({'_id':data['_id']}):
    return jsonify(status=400, msg='no this sf', data=None), 400
  start_pod(data)
  return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/scaleDown',methods=['POST'])
def scale_down():
  data = json.loads(request.get_data().decode('utf-8'))
  if not mongo.db.sf_set.find_one({'_id':data['_id']}):
    return jsonify(status=400, msg='no this sf', data=None), 400
  sf_instance_set = mongo.db.sf_instance_set
  num = sf_instance_set.find({'sfId': data['sfId']}).count()
  sf_instance_set.update_one({'sfId': data['sfId']},{'$set':{'stop': True}})
  return jsonify(status=200, msg='success', data=None), 200

def start_pod(data):
  instanceId = str(uuid.uuid1()).replace('-', '')
  record={
    '_id': instanceId,
    'sfId': data['_id'],
    'status': 'created',
    'time': time.time(),
    'stop': False
  }

  pod=client.V1Pod(api_version='v1',kind='Pod')
  pod.metadata=client.V1ObjectMeta(name=instanceId)

  container1=client.V1Container(name="sff",image="sff:latest")
  container1.args=[app.config['SERVER'], data['_id'], instanceId]
  container1.image_pull_policy='IfNotPresent'
  container2=client.V1Container(name='sf',image=data['image'])
  container2.image_pull_policy='IfNotPresent'
  containers = [container1,container2]

  spec=client.V1PodSpec(containers=containers)
  pod.spec = spec
  v1.create_namespaced_pod(namespace="default",body=pod)
  mongo.db.sf_instance_set.insert(record)

@app.route('/api/SF/<_id>',methods=['DELETE'])
def delete_sf(_id):
  sf_instance_set = mongo.db.sf_instance_set
  instances = sf_instance_set.find({'sfId': _id})
  for instance in instances:
    try:
      v1.delete_namespaced_pod(name=instance['_id'], namespace="default", body=client.V1DeleteOptions())
    except:
      pass
  sf_instance_set.remove({'sfId':_id})
  mongo.db.sf_set.remove({'_id':_id})
  return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/SF',methods=['PUT'])
def update_sf():
  data = json.loads(request.get_data().decode('utf-8'));
  sf_set = mongo.db.sf_set
  if not sf_set.find_one({'_id':data['_id']}):
    return jsonify(status=400, msg='not find this sf', data=None), 400
  sf_set.update({"_id": data['_id']},{"$set":data})
  return jsonify(status=200, msg='success', data=None), 200

@app.route('/api/SF/<_id>',methods=['GET'])
def get_sf(_id):
  sf_set = mongo.db.sf_set
  sf = sf_set.find_one({'_id': _id})
  instances = mongo.db.sf_instance_set.find({'sfId':sf['_id']})
  sf['instances'] = instances
  return jsonify(status=200, msg='success', data=sf), 200

@app.route('/api/SFs',methods=['GET'])
def get_sfs():
  sf_set = mongo.db.sf_set
  sfs = list(sf_set.find())
  sf_instance_set = mongo.db.sf_instance_set
  for sf in sfs:
    instances=list(sf_instance_set.find({'sfId':sf['_id']}))
    sf['instances'] = instances
  return jsonify(status=200, msg='success', data=sfs), 200


lock = Lock()
#SFC
@app.route('/api/SFC',methods=['POST'])
def add_sfc():
  data = json.loads(request.get_data().decode('utf-8'));
  print(data['name'])
  with lock:
    sfc_set = mongo.db.sfc_set
    if sfc_set.find_one({'name':data['name']}):
      return jsonify(status=400, msg='sfc already exist', data=None), 400
    maxItem = sfc_set.find().sort([('id', -1)]).limit(1)
    sfc_id=1
    for item in maxItem:
      sfc_id = item['id']+1
    SFs = data.get('SFs')
    records = []
    for i in range(0,len(SFs)):
      if i<len(SFs)-1:
        next = SFs[i+1]['_id']
      else:
        next = None
      record={
        '_id': str(uuid.uuid1()).replace('-', ''),
        'id': sfc_id,
        'name': data['name'],
        'order': i+1,
        'present': SFs[i]['_id'],
        'next': next
      }
      records.append(record)
    sfc_set.insert_many(records)
  return jsonify(status=200, msg='success', data={id:sfc_id}), 200

@app.route('/api/SFC/<id>',methods=['DELETE'])
def delete_sfc(id):
  sfc_set = mongo.db.sfc_set
  sfc_set.remove({'id':id})
  return jsonify(status=200, msg='success', data=None), 200


@app.route('/api/SFC/<id>',methods=['GET'])
def get_sfc(id):
  sfc_set = mongo.db.sfc_set
  sfcs = sfc_set.aggregate([{'$match':{'id':id}},{'$group':{'_id':'$id','sfs':{'$push':'$present'}}}])
  return jsonify(status=200, msg='success', data=sfcs), 200

@app.route('/api/SFCs',methods=['GET'])
def get_sfcs():
  sfc_set = mongo.db.sfc_set
  sfcs = list(sfc_set.aggregate([{'$group':{'_id':'$id','sfs':{'$push':'$present'}}}]))
  return jsonify(status=200, msg='success', data=sfcs), 200

@app.route('/api/heartbeat',methods=['POST'])
def heartbeat():
  data = json.loads(request.get_data().decode('utf-8'));
  t = time.time()
  data['time'] = t
  data['status'] = 'running'
  sf_instance_set = mongo.db.sf_instance_set
  instanceId = data.pop('instanceId')
  sf_instance_set.update({"_id": instanceId},{"$set":data})

  next_hops={}
  SFCs = list(mongo.db.sfc_set.find({'present':data['sfId']}))
  for sfc in SFCs:
    if sfc['next'] == None:
      instances = None
    else:
      instances = list(sf_instance_set.find({'sfId': sfc['next'], 'status':'running', 'stop': False}))
    next_hops[sfc['id']] = instances
  # print(next_hops)
  return jsonify(status=200, msg='success', data=next_hops), 200

@socketio.on('connect', namespace='/socket/client')
def client_connect():
    logger.info('client connect:'+request.sid)

@socketio.on('disconnect', namespace='/socket/client')
def client_disconnect():
    logger.info('client disconnected:'+request.sid)


if __name__ == '__main__':
    app.run(host='0.0.0.0',port=5000,debug=False,threaded=True)
    # socketio.run(app)
