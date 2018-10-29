from pymongo import MongoClient
from kubernetes import client, config
import json, time, uuid

SERVER = '192.168.43.128:5000'
MAX_QUEUE_SIZE = '1000'

mongo = MongoClient('localhost', 27017)
db = mongo.mysfc

config.load_kube_config()
v1=client.CoreV1Api()

scale_time={}

def scale_up(sfId):
	sf = db.sf_set.find_one({'_id':sfId})
	if not sf.get('autoscale'):
		return
	if db.sf_instance_set.find({'sfId':sfId}).count() >= 5:
		return

	t = time.time()
	if scale_time.get(sfId):
		if t - scale_time.get(sfId) < 10:
			return
	scale_time[sfId] = t

	instanceId = str(uuid.uuid1()).replace('-', '')[:12]
	record={
	'_id': instanceId,
	'sfId': sfId,
	'image': sf['image'],
	'policy': sf['policy'],
	'cpu': sf['cpu'],
	'memory': sf['memory'],
	'status': 'creating',
	'time': time.time(),
	'stop': False,
	"ip": None,
    "receivedPackets": 0,
    "qsize": 0,
    "speed": 0
	}
	db.sf_instance_set.insert(record)

	next_hops={}
	sfs = list(mongo.db.sfc_set.find({'sfId':sfId}))
	for sf in sfs:
		if sf['next'] == None:
			instances = None
		else:
			instances = list(db.sf_instance_set.find({'sfId': sf['next'], 'status':'running'}))
		next_hops[sf['sfcId']] = instances

	args = {
	'server': SERVER,
	'sfId': sf['_id'],
	'instanceId': instanceId,
	'policy': sf['policy'],
	'max_queue_size': MAX_QUEUE_SIZE,
	'next_hops': next_hops
	}

	pod=client.V1Pod(api_version='v1',kind='Pod')
	pod.metadata=client.V1ObjectMeta(name=sfId+'-'+instanceId)

	# container1=client.V1Container(name="sff",image="sff:latest")
	# container1.args=[app.config['SERVER'], data['_id'], instanceId]
	# container1.image_pull_policy='IfNotPresent'
	# container2=client.V1Container(name='sf',image=data['image'])
	# container2.image_pull_policy='IfNotPresent'
	# containers = [container1,container2]
	resources=client.V1ResourceRequirements(limits={'cpu': sf['cpu'],'memory': sf['memory']},requests={'cpu': sf['cpu'],'memory': sf['memory']})
	container1=client.V1Container(name="sff",image=sf['image'],resources=resources)
	container1.args=[json.dumps(args)]
	container1.image_pull_policy='IfNotPresent'
	containers = [container1]

	spec=client.V1PodSpec(containers=containers)
	pod.spec = spec
	v1.create_namespaced_pod(namespace="default",body=pod)


def scale_down():
	pass

def check():
	while(True):
		try:
			res = db.sf_instance_set.aggregate([{"$group" : {"_id" : "$sfId", "avg_qsize" : {"$avg" : "$qsize"}}}])
			for item in res:
				if item['_id'] != 'dispatcher':
					print(item, end=' ')
					if item['avg_qsize'] > 500:
						print('scale up')
						scale_up(item['_id'])
					elif item['avg_qsize'] < 50:
						print('scale down')
						scale_down()
					else:
						print()
		except Exception as e:
			print(e)
		time.sleep(3)


if __name__ == '__main__':
	check()