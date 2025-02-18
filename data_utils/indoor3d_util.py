import numpy as np
import glob
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
sys.path.append(BASE_DIR)

DATA_PATH = os.path.join(ROOT_DIR, 'data', 's3dis', 'Stanford3dDataset_v1.2_Aligned_Version')
g_classes = [x.rstrip() for x in open(os.path.join(BASE_DIR, 'meta/class_names.txt'))]
g_class2label = {cls: i for i, cls in enumerate(g_classes)}
g_class2color = {'ceiling': [0, 255, 0],
                 'floor': [0, 0, 255],
                 'wall': [0, 255, 255],
                 'beam': [255, 255, 0],
                 'column': [255, 0, 255],
                 'window': [100, 100, 255],
                 'door': [200, 200, 100],
                 'table': [170, 120, 200],
                 'chair': [255, 0, 0],
                 'sofa': [200, 100, 100],
                 'bookcase': [10, 200, 100],
                 'board': [200, 200, 200],
                 'clutter': [50, 50, 50]}  # not used except in visualization
g_label2color = {g_classes.index(cls): g_class2color[cls] for cls in
                 g_classes}  # This is not used except in visualization


# -----------------------------------------------------------------------------
# CONVERT ORIGINAL DATA TO OUR DATA_LABEL FILES
# -----------------------------------------------------------------------------

def collect_point_label(anno_path, out_filename, file_format='txt'):
    """ Convert original dataset files to data_label file (each line is XYZRGBL).
        We aggregated all the points from each instance in the room.

    Args:
        anno_path: path to annotations. e.g. Area_1/office_2/Annotations/
        out_filename: path to save collected points and labels (each line is XYZRGBL)
        file_format: txt or numpy, determines what file format to save.
    Returns:
        None
    Note:
        the points are shifted before save, the most negative point is now at origin.
    """
    points_list = []
    for f in glob.glob(os.path.join(anno_path, '*.txt')):
        cls = os.path.basename(f).split('_')[0]
        print(f)
        if cls not in g_classes:  # note: in some room there is 'staris' class..
            cls = 'clutter'

        points = np.loadtxt(f)
        labels = np.ones((points.shape[0], 1)) * g_class2label[cls]
        points_list.append(np.concatenate([points, labels], 1))  # Nx7

    data_label = np.concatenate(points_list, 0)
    xyz_min = np.amin(data_label, axis=0)[0:3]
    data_label[:, 0:3] -= xyz_min

    if file_format == 'txt':
        fout = open(out_filename, 'w')
        for i in range(data_label.shape[0]):
            fout.write('%f %f %f %d %d %d %d\n' % \
                       (data_label[i, 0], data_label[i, 1], data_label[i, 2],
                        data_label[i, 3], data_label[i, 4], data_label[i, 5],
                        data_label[i, 6]))
        fout.close()
    elif file_format == 'numpy':
        np.save(out_filename, data_label)
    else:
        print('ERROR!! Unknown file format: %s, please use txt or numpy.' % \
              file_format)
        exit()


def data_to_obj(data, name='example.obj', no_wall=True):
    fout = open(name, 'w')
    label = data[:, -1].astype(int)
    for i in range(data.shape[0]):
        if no_wall and ((label[i] == 2) or (label[i] == 0)):
            continue
        fout.write('v %f %f %f %d %d %d\n' % \
                   (data[i, 0], data[i, 1], data[i, 2], data[i, 3], data[i, 4], data[i, 5]))
    fout.close()


# def point_label_to_obj(input_filename, out_filename, label_color=True, easy_view=False, no_wall=False):
#     """ For visualization of a room from data_label file,
# 	input_filename: each line is X Y Z R G B L
# 	out_filename: OBJ filename,
#             visualize input file by coloring point with label color
#         easy_view: only visualize furnitures and floor
#     """
#     data_label = np.loadtxt(input_filename)
#     data = data_label[:, 0:6]
#     label = data_label[:, -1].astype(int)
#     fout = open(out_filename, 'w')
#     for i in range(data.shape[0]):
#         color = g_label2color[label[i]]
#         if easy_view and (label[i] not in g_easy_view_labels):
#             continue
#         if no_wall and ((label[i] == 2) or (label[i] == 0)):
#             continue
#         if label_color:
#             fout.write('v %f %f %f %d %d %d\n' % \
#                        (data[i, 0], data[i, 1], data[i, 2], color[0], color[1], color[2]))
#         else:
#             fout.write('v %f %f %f %d %d %d\n' % \
#                        (data[i, 0], data[i, 1], data[i, 2], data[i, 3], data[i, 4], data[i, 5]))
#     fout.close()


# -----------------------------------------------------------------------------
# PREPARE BLOCK DATA FOR DEEPNETS TRAINING/TESTING
# -----------------------------------------------------------------------------

def sample_data(data, num_sample):
    """ data is in N x ...
        we want to keep num_samplexC of them.
        if N > num_sample, we will randomly keep num_sample of them.
        if N < num_sample, we will randomly duplicate samples.
    """
    N = data.shape[0]
    if (N == num_sample):
        return data, range(N)
    elif (N > num_sample):
        sample = np.random.choice(N, num_sample)
        return data[sample, ...], sample
    else:
        sample = np.random.choice(N, num_sample - N)
        dup_data = data[sample, ...]
        return np.concatenate([data, dup_data], 0), list(range(N)) + list(sample)


def sample_data_label(data, label, num_sample):
    new_data, sample_indices = sample_data(data, num_sample)
    new_label = label[sample_indices]
    return new_data, new_label


def room2blocks(data, label, num_point, block_size=1.0, stride=1.0,
                random_sample=False, sample_num=None, sample_aug=1):
    """ Prepare block training data.
    Args:
        data: N x 6 numpy array, 012 are XYZ in meters, 345 are RGB in [0,1]
            assumes the data is shifted (min point is origin) and aligned
            (aligned with XYZ axis)
        label: N size uint8 numpy array from 0-12
        num_point: int, how many points to sample in each block
        block_size: float, physical size of the block in meters
        stride: float, stride for block sweeping
        random_sample: bool, if True, we will randomly sample blocks in the room
        sample_num: int, if random sample, how many blocks to sample
            [default: room area]
        sample_aug: if random sample, how much aug
    Returns:
        block_datas: K x num_point x 6 np array of XYZRGB, RGB is in [0,1]
        block_labels: K x num_point x 1 np array of uint8 labels
        
    TODO: for this version, blocking is in fixed, non-overlapping pattern.
    """
    assert (stride <= block_size)

    limit = np.amax(data, 0)[0:3]

    # Get the corner location for our sampling blocks    
    xbeg_list = []
    ybeg_list = []
    if not random_sample:
        num_block_x = int(np.ceil((limit[0] - block_size) / stride)) + 1
        num_block_y = int(np.ceil(collect_point_label(limit[1] - block_size) / stride)) + 1
        for i in range(num_block_x):
            for j in range(num_block_y):
                xbeg_list.append(i * stride)
                ybeg_list.append(j * stride)
    else:
        num_block_x = int(np.ceil(limit[0] / block_size))
        num_block_y = int(np.ceil(limit[1] / block_size))
        if sample_num is None:
            sample_num = num_block_x * num_block_y * sample_aug
        for _ in range(sample_num):
            xbeg = np.random.uniform(-block_size, limit[0])
            ybeg = np.random.uniform(-block_size, limit[1])
            xbeg_list.append(xbeg)
            ybeg_list.append(ybeg)

    # Collect blocks
    block_data_list = []
    block_label_list = []
    idx = 0
    for idx in range(len(xbeg_list)):
        xbeg = xbeg_list[idx]
        ybeg = ybeg_list[idx]
        xcond = (data[:, 0] <= xbeg + block_size) & (data[:, 0] >= xbeg)
        ycond = (data[:, 1] <= ybeg + block_size) & (data[:, 1] >= ybeg)
        cond = xcond & ycond
        if np.sum(cond) < 100:  # discard block if there are less than 100 pts.
            continue

        block_data = data[cond, :]
        block_label = label[cond]

        # randomly subsample data
        block_data_sampled, block_label_sampled = \
            sample_data_label(block_data, block_label, num_point)
        block_data_list.append(np.expand_dims(block_data_sampled, 0))
        block_label_list.append(np.expand_dims(block_label_sampled, 0))

    return np.concatenate(block_data_list, 0), \
        np.concatenate(block_label_list, 0)


def room2blocks_plus(data_label, num_point, block_size, stride,
                     random_sample, sample_num, sample_aug):
    """ room2block with input filename and RGB preprocessing.
    """
    data = data_label[:, 0:6]
    data[:, 3:6] /= 255.0
    label = data_label[:, -1].astype(np.uint8)

    return room2blocks(data, label, num_point, block_size, stride,
                       random_sample, sample_num, sample_aug)


def room2blocks_wrapper(data_label_filename, num_point, block_size=1.0, stride=1.0,
                        random_sample=False, sample_num=None, sample_aug=1):
    if data_label_filename[-3:] == 'txt':
        data_label = np.loadtxt(data_label_filename)
    elif data_label_filename[-3:] == 'npy':
        data_label = np.load(data_label_filename)
    else:
        print('Unknown file type! exiting.')
        exit()
    return room2blocks_plus(data_label, num_point, block_size, stride,
                            random_sample, sample_num, sample_aug)


def room2blocks_plus_normalized(data_label, num_point, block_size, stride,
                                random_sample, sample_num, sample_aug):
    """ room2block, with input filename and RGB preprocessing.
        for each block centralize XYZ, add normalized XYZ as 678 channels
    """
    data = data_label[:, 0:6]
    data[:, 3:6] /= 255.0
    label = data_label[:, -1].astype(np.uint8)
    max_room_x = max(data[:, 0])
    max_room_y = max(data[:, 1])
    max_room_z = max(data[:, 2])

    data_batch, label_batch = room2blocks(data, label, num_point, block_size, stride,
                                          random_sample, sample_num, sample_aug)
    new_data_batch = np.zeros((data_batch.shape[0], num_point, 9))
    for b in range(data_batch.shape[0]):
        new_data_batch[b, :, 6] = data_batch[b, :, 0] / max_room_x
        new_data_batch[b, :, 7] = data_batch[b, :, 1] / max_room_y
        new_data_batch[b, :, 8] = data_batch[b, :, 2] / max_room_z
        minx = min(data_batch[b, :, 0])
        miny = min(data_batch[b, :, 1])
        data_batch[b, :, 0] -= (minx + block_size / 2)
        data_batch[b, :, 1] -= (miny + block_size / 2)
    new_data_batch[:, :, 0:6] = data_batch
    return new_data_batch, label_batch


def room2blocks_wrapper_normalized(data_label_filename, num_point, block_size=1.0, stride=1.0,
                                   random_sample=False, sample_num=None, sample_aug=1):
    if data_label_filename[-3:] == 'txt':
        data_label = np.loadtxt(data_label_filename)
    elif data_label_filename[-3:] == 'npy':
        data_label = np.load(data_label_filename)
    else:
        print('Unknown file type! exiting.')
        exit()
    return room2blocks_plus_normalized(data_label, num_point, block_size, stride,
                                       random_sample, sample_num, sample_aug)


def room2samples(data, label, sample_num_point):
    """ Prepare whole room samples.

    Args:
        data: N x 6 numpy array, 012 are XYZ in meters, 345 are RGB in [0,1]
            assumes the data is shifted (min point is origin) and
            aligned (aligned with XYZ axis)
        label: N size uint8 numpy array from 0-12
        sample_num_point: int, how many points to sample in each sample
    Returns:
        sample_datas: K x sample_num_point x 9
                     numpy array of XYZRGBX'Y'Z', RGB is in [0,1]
        sample_labels: K x sample_num_point x 1 np array of uint8 labels
    """
    N = data.shape[0]
    order = np.arange(N)
    np.random.shuffle(order)
    data = data[order, :]
    label = label[order]

    batch_num = int(np.ceil(N / float(sample_num_point)))
    sample_datas = np.zeros((batch_num, sample_num_point, 6))
    sample_labels = np.zeros((batch_num, sample_num_point, 1))

    for i in range(batch_num):
        beg_idx = i * sample_num_point
        end_idx = min((i + 1) * sample_num_point, N)
        num = end_idx - beg_idx
        sample_datas[i, 0:num, :] = data[beg_idx:end_idx, :]
        sample_labels[i, 0:num, 0] = label[beg_idx:end_idx]
        if num < sample_num_point:
            makeup_indices = np.random.choice(N, sample_num_point - num)
            sample_datas[i, num:, :] = data[makeup_indices, :]
            sample_labels[i, num:, 0] = label[makeup_indices]
    return sample_datas, sample_labels


def room2samples_plus_normalized(data_label, num_point):
    """ room2sample, with input filename and RGB preprocessing.
        for each block centralize XYZ, add normalized XYZ as 678 channels
    """
    data = data_label[:, 0:6]
    data[:, 3:6] /= 255.0
    label = data_label[:, -1].astype(np.uint8)
    max_room_x = max(data[:, 0])
    max_room_y = max(data[:, 1])
    max_room_z = max(data[:, 2])
    # print(max_room_x, max_room_y, max_room_z)

    data_batch, label_batch = room2samples(data, label, num_point)
    new_data_batch = np.zeros((data_batch.shape[0], num_point, 9))
    for b in range(data_batch.shape[0]):
        new_data_batch[b, :, 6] = data_batch[b, :, 0] / max_room_x
        new_data_batch[b, :, 7] = data_batch[b, :, 1] / max_room_y
        new_data_batch[b, :, 8] = data_batch[b, :, 2] / max_room_z
        # minx = min(data_batch[b, :, 0])
        # miny = min(data_batch[b, :, 1])
        # data_batch[b, :, 0] -= (minx+block_size/2)
        # data_batch[b, :, 1] -= (miny+block_size/2)
    new_data_batch[:, :, 0:6] = data_batch
    return new_data_batch, label_batch


def room2samples_wrapper_normalized(data_label_filename, num_point):
    if data_label_filename[-3:] == 'txt':
        data_label = np.loadtxt(data_label_filename)
    elif data_label_filename[-3:] == 'npy':
        data_label = np.load(data_label_filename)
    else:
        print('Unknown file type! exiting.')
        exit()
    return room2samples_plus_normalized(data_label, num_point)
  