import os
import sys
import numpy as np
import tensorflow.compat.v1 as tf
import matplotlib.pyplot as plt

from tqdm import tqdm
from config import cfg
from utils import load_imdb, load_ag, record
from model import CapsNet

def save_to():
	if not os.path.exists(cfg.results):
		os.mkdir(cfg.results)

	if cfg.is_training:
		loss = cfg.results + '/loss.csv'
		train_acc = cfg.results + '/train_acc.csv'
		val_acc = cfg.results + '/val_acc.csv'

		if os.path.exists(loss):
			os.remove(loss)
		if os.path.exists(train_acc):
			os.remove(train_acc)
		if os.path.exists(val_acc):
			os.remove(val_acc)

		f_loss = open(loss, 'w')
		f_loss.write('step, loss\n')

		f_train_acc = open(train_acc, 'w')
		f_train_acc.write('step, train_acc\n')

		f_val_acc = open(val_acc, 'w')
		f_val_acc.write('step, val_acc\n')

		return f_loss, f_train_acc, f_val_acc

	else:
		test_acc = cfg.results + '/test_acc.csv'

		if os.path.exists(test_acc):
			os.remove(test_acc)

		f_test_acc = open(test_acc, 'w')
		f_test_acc.write('test_acc\n')
		return f_test_acc


def train(model, supervisor):
	losses = []
	accs = []
	steps = []
	val_accs = []
	val_steps = []

	if cfg.dataset == 'imdb':
		trX, trY, num_tr_batch, valX, valY, num_val_batch = load_imdb(cfg.batch_size, cfg.words, cfg.length, is_training=True)
	elif cfg.dataset == 'ag':
		trX, trY, num_tr_batch, valX, valY, num_val_batch = load_ag(cfg.batch_size, cfg.length, is_training=True)

	f_loss, f_train_acc, f_val_acc = save_to()
	config = tf.ConfigProto()
	config.gpu_options.allow_growth = True

	with supervisor.managed_session(config=config) as sess:
		print('\nSupervisor Prepared')

		for epoch in range(cfg.epoch):
			print('Training for epoch ' + str(epoch+1) + '/' + str(cfg.epoch) + ':')

			if supervisor.should_stop():
				print('Supervisor stopped')
				break

			for step in tqdm(range(num_tr_batch), total=num_tr_batch, ncols=70, leave=False, unit='b'):
				start = step * cfg.batch_size
				end = start + cfg.batch_size
				global_step = epoch * num_tr_batch + step

				if global_step % cfg.train_sum_freq == 0:
					_, loss, train_acc, summaries = sess.run([model.train_op, model.total_loss, model.accuracy, model.train_summary])

					losses.append(loss)
					accs.append(train_acc)
					steps.append(global_step)

					assert not np.isnan(loss), 'loss is nan...'
					supervisor.summary_writer.add_summary(summaries, global_step)

					f_loss.write(str(global_step) + ',' + str(loss) + '\n')
					f_loss.flush()
					f_train_acc.write(str(global_step) + ',' + str(train_acc) + '\n')
					f_train_acc.flush()

				else:
					sess.run(model.train_op)

				if cfg.val_sum_freq != 0 and (global_step) % cfg.val_sum_freq == 0:
					val_acc = 0
					for i in range(num_val_batch):
						start = i * cfg.batch_size
						end = start + cfg.batch_size
						acc = sess.run(model.accuracy, {model.X: valX[start:end], model.Y: valY[start:end]})
						val_acc += acc
					val_acc = val_acc / num_val_batch
					f_val_acc.write(str(global_step) + ',' + str(val_acc) + '\n')
					f_val_acc.flush()

					val_accs.append(val_acc)
					val_steps.append(global_step)

			if (epoch + 1) % cfg.save_freq == 0 and cfg.save:
				supervisor.saver.save(sess, cfg.logdir + '/model_epoch_{0:.4g}_step_{1:.2g}'.format(epoch, global_step))

		if cfg.save:
			supervisor.saver.save(sess, cfg.logdir + '/model_epoch_{0:.4g}_step_{1:.2g}'.format(epoch, global_step))

		f, (ax1, ax2) = plt.subplots(1, 2, sharey=False)
		ax1.set_title('Loss')
		ax1.plot(steps, losses)
		ax1.set_xlabel('Global step')
		ax1.set_ylabel('Loss')

		ax2.set_title('Accuracy')
		ax2.plot(val_steps, val_accs, color='b', label='val_accs')
		ax2.plot(steps, accs, color='r', label='train_accs')
		ax2.set_xlabel('Global step')
		ax2.set_ylabel('Accuracy')
		ax2.legend(loc='lower right')
		plt.show()

		f_loss.close()
		f_train_acc.close()
		f_val_acc.close()

		return losses[-1], accs[-1]


def evaluation(model, supervisor):
	if cfg.dataset == 'imdb':
		teX, teY, num_te_batch = load_imdb(cfg.batch_size, cfg.words, cfg.length, is_training=False)
	elif cfg.dataset == 'ag':
		teX, teY, num_te_batch = load_ag(cfg.batch_size, cfg.length, is_training=False)

	cfg.is_training = False
	f_test_acc = save_to()

	with supervisor.managed_session(config=tf.ConfigProto(allow_soft_placement=True)) as sess:
		supervisor.saver.restore(sess, tf.train.latest_checkpoint(cfg.logdir))
		tf.logging.info('Model restored...')

		test_acc = 0

		for i in tqdm(range(num_te_batch), total=num_te_batch, ncols=70, leave=False, unit='b'):
			start = i * cfg.batch_size
			end = start + cfg.batch_size
			acc = sess.run(model.accuracy, {model.X: teX[start:end], model.Y: teY[start:end]})
			test_acc += acc
		test_acc = test_acc / num_te_batch
		f_test_acc.write(str(test_acc))
		f_test_acc.close()
		print('Test accuracy saved to ' + cfg.results + '/test_acc.csv')
		print('Test accuracy:', test_acc)

	return test_acc


def test(model, supervisor):
	teX, teY, num_te_batch = load_ag(cfg.batch_size, cfg.length, is_training=False)
	teX = teX[0:64]
	teY = teY[0:64]

	with supervisor.managed_session(config=tf.ConfigProto(allow_soft_placement=True)) as sess:
		supervisor.saver.restore(sess, tf.train.latest_checkpoint(cfg.logdir))

		out, acc = sess.run([model.logits, model.accuracy], {model.X: teX, model.Y: teY})
		print(np.argmax(out, axis=1), acc, '%')

def main(_):
	tf.logging.info('Loading Graph...')
	model = CapsNet()
	tf.logging.info('Graph loaded')

	sv = tf.train.Supervisor(graph=model.graph, logdir=cfg.logdir, save_model_secs=0)

	if not cfg.is_training:
		#_ = evaluation(model, sv)
		_ = test(model, sv)

	else:
		tf.logging.info('Start is_training...')
		loss, acc = train(model, sv)
		tf.logging.info('Training done')
		
		if cfg.save:
			test_acc = evaluation(model, sv)
			record(loss, acc, test_acc)


if __name__ == '__main__':
	tf.app.run()
