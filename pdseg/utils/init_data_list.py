import os
import numpy as np


def build_datasets(base, val_ratio=0.2):
    with open(base+'labels.txt', 'w') as f:
        for i in range(20):
            f.write(str(i)+'\n')

    imgs = os.listdir(os.path.join(base, 'train/'))
    np.random.seed(5)
    np.random.shuffle(imgs)
    val_num = int(val_ratio * len(imgs))

    with open(os.path.join(base, 'train_list.txt'), 'w+') as f:
        for pt in imgs[:-val_num]:
            img = 'train/'+pt
            ann = 'train_label/'+pt.replace('.jpg', '.png')
            info = img + ' ' + ann + '\n'
            f.write(info)

    with open(os.path.join(base, 'val_list.txt'), 'w+') as f:
        for pt in imgs[-val_num:]:
            img = 'train/'+pt
            ann = 'train_label/'+pt.replace('.jpg', '.png')
            info = img + ' ' + ann + '\n'
            f.write(info)

    with open(os.path.join(base, 'test_list.txt'), 'w+') as f:
        for pt in os.listdir(base+'test/'):
            img = 'test/'+pt
            info = img + '\n'
            f.write(info)


if __name__ == '__main__':
    path = r"/data01/zxl/hualu-laneline-detection/Semi-Final/"
    build_datasets(path)
