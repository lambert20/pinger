import ipaddress
import getopt
import sys
import subprocess
import threading
import time
import copy
import os
import platform
import json

stime = time.time()


class Pinger(object):
    status = {'time': [], 'alive': [], 'dead': []}  # Populated while we are running
    hosts = []  # List of all hosts/ips in our input queue

    # How many ping process at the time.
    thread_count = 4

    # Lock object to keep track the threads in loops, where it can potentially be race conditions.
    lock = threading.Lock()

    def ping(self, ip):
        # Use the system ping command with count of 1 and wait time of 1.

        if platform.system() == 'Windows':
            ret = subprocess.call(["ping", "-n", "2", "-w", "300", ip],
                                  stdout=open(os.devnull, "wb"), stderr=open(os.devnull, "wb"))
        else:  # platform.platform().find('darwin') or platform.platform().find('linux'):
            ret = subprocess.call(['ping', '-c', '2', '-W', '1', ip],
                                  stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
        return ret == 0  # Return True if our ping command succeeds

    def pop_queue(self):
        ip = None

        self.lock.acquire()  # Grab or wait+grab the lock.

        if self.hosts:
            ip = self.hosts.pop()

        self.lock.release()  # Release the lock, so another thread could grab it.

        return ip

    def dequeue(self):
        while True:
            ip = self.pop_queue()

            if not ip:
                return None

            result = 'alive' if self.ping(ip) else 'dead'
            self.status[result].append(ip)

    def start(self):
        threads = []

        for i in range(self.thread_count):
            # Create self.thread_count number of threads that together will
            # cooperate removing every ip in the list. Each thread will do the
            # job as fast as it can.
            t = threading.Thread(target=self.dequeue)
            t.start()
            threads.append(t)

        # Wait until all the threads are done. .join() is blocking.
        [t.join() for t in threads]

        return self.status


def record_json_on_outfile(outputfile, cur_result_as_json):
    f = open(outputfile, 'a')
    f.write(cur_result_as_json)
    f.close()
    return


def add_ping_results_list_to_mongo(input_list):
    import pymongo

    db_uri = 'mongodb://192.168.0.92:27017/'
    con = pymongo.MongoClient(db_uri)
    db = con.test.database
    pingresults = db.pingresults

    for i in range(len(input_list)):
        pingresults.insert(input_list[i])


# for x in pingresults.find():
#        print(x)
#       pingresults.remove(x)

def diff(first, second):
    second = set(second)
    return [item for item in first if item not in second]


def get_opts(argv):
    #    inputfile = 'ip_list_inputfile.txt'
    inputfile = ''
    outputfile = ''
    threads = 32
    subnets = ['192.168.0.0/26']
    count = 40
    try:
        opts, args = getopt.getopt(argv, "hs:c:t:c:i:o", [ "subnet=", "count=", "threads", "ifile=", "ofile="])
    except getopt.GetoptError:
        print('test.py -s <subnet list> -c <count> -t <threads> -i <inputfile> -o <outputfile>')
        exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print('test.py -i <inputfile> -o <outputf'
                  'ile> -s <subnet>')
            exit()
        elif opt in ("-i", "--ifile"):
            inputfile = arg
        elif opt in ("-o", "--ofile"):
            outputfile = arg
        elif opt in ("-t", "--threads"):
            threads = arg
        elif opt in ("-s", "--subnet"):
            subnets = subnets + arg.split(',')
        elif opt in ("-c", "--count"):
            count = arg

    if inputfile != '':
        with open(inputfile) as f:
            read_data = f.read()
            subnets = subnets + read_data.replace('\t', '').replace('\n', '').split(',')

    return inputfile, outputfile, subnets, int(count), int(threads)


def main(argv):
    """business logic for when running this module as the primary one!"""

    (inputfile, outputfile, subnets, ping_count,thread_count) = get_opts(argv[1:])

    print('Starting ', time.asctime(time.localtime()), ' Program=', argv[0])
    print('  ping_count=', ping_count, '   thread_count=', thread_count,end='')
    print('  input_file_name=', inputfile, '    output_file_name=', outputfile)
    print('  subnet_list=', subnets)

    l0 = []
    l1 = []

    if len(subnets) > 0:
        for net in subnets:
            l0.append((list(ipaddress.IPv4Network(net))))

    for subnet_list in l0:
        for ip_str in subnet_list:
            l1 = l1 + [str(ip_str)]

    ping_object = Pinger()
    ping_results_list = []

    for a in range(ping_count):
        ping_object.thread_count = thread_count
        ping_object.hosts = l1[:]
        cur_result = ping_object.start()
        cur_result['time'].append(time.time())
        cur_result_as_json = json.dumps(cur_result, sort_keys=True, indent=4)
        if len(cur_result_as_json) > 0 and len(outputfile) > 0:
            record_json_on_outfile(outputfile, cur_result_as_json)
        # print(cur_result_as_json)
        ping_results_list.append(copy.deepcopy(cur_result))
        while len(ping_results_list) > 2:
            ping_results_list = ping_results_list[1:]

        if len(ping_results_list) > 1:
            diff_dead = diff(ping_results_list[1]['dead'], ping_results_list[0]['dead'])
            print(time.asctime(time.localtime()), ' alive= ', len(list(ping_results_list[1]['alive'])), 'dead= ',
                  len(list(ping_results_list[1]['dead'])), end='')
            diff_alive = diff(ping_results_list[1]['alive'], ping_results_list[0]['alive'])
            if len(diff_alive) > 0:
                print('  born', diff_alive, 'died', diff_dead)
            elif len(diff_dead) > 0:
                print('  born', diff_alive, 'died', diff_dead)
            else:
                print('')

                #            add_ping_results_list_to_mongo([ping_results_list[1]])
        else:
            print(time.asctime(time.localtime()), ' starting alive= ', len(list(ping_results_list[0]['alive'])))
            print(time.asctime(time.localtime()), ' starting alive list= ', ping_results_list[0]['alive'])

        # clear lists active and dead
        for b in range(len(ping_object.status['alive'])):
            ping_object.status['alive'].pop()
        for b in range(len(ping_object.status['dead'])):
            ping_object.status['dead'].pop()
        for b in range(len(ping_object.status['time'])):
            ping_object.status['time'].pop()

    print(time.asctime(time.localtime()), ' finishing alive= ', ping_results_list[1]['alive'])
    print("Seconds", time.time() - stime)
    return 0


if __name__ == "__main__":
    main(sys.argv[:])
